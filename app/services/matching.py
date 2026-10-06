"""Hybrid matching: deterministic rule scores + embedding similarity (+ optional LLM explanation text).

The numeric score never depends on LLM output, so it is reproducible.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import MatchingError
from app.db.models import Job, JobMatch
from app.llm.provider import LLMProvider
from app.schemas import JDAnalysis
from app.services.embeddings import cosine, ensure_embedding
from app.services.jd_analyzer import heuristic_analyze
from app.services.profile import ProfileBundle
from app.services.skills import canonical

_EDU = {"none": 0, "bachelor": 1, "master": 2, "phd": 3}
_TOK = re.compile(r"[a-z0-9+#]{2,}")


def recommendation_for(score: float, s: Settings) -> str:
    if score >= s.t_excellent:
        return "Excellent"
    if score >= s.t_strong:
        return "Strong"
    if score >= s.t_good:
        return "Good"
    if score >= s.t_weak:
        return "Weak"
    return "Not Recommended"


def _highest_edu(b: ProfileBundle) -> int | None:
    if not b.education:
        return None
    best = 0
    for e in b.education:
        d = (e.degree or "").lower()
        lvl = 3 if re.search(r"ph\.?d|doctor", d) else 2 if re.search(r"master|msc|\bm\.?s\b|mba", d) else \
            1 if re.search(r"bachelor|bsc|\bb\.?s\b|\bbs\b|\bbe\b|b\.tech|undergrad", d) else 0
        best = max(best, lvl)
    return best


def compute_match(job: Job, analysis: JDAnalysis, b: ProfileBundle, provider: LLMProvider,
                  settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    if not b.profile:
        raise MatchingError("Complete your profile before matching.")
    declared, evidenced = b.declared, b.evidenced
    known = declared | evidenced
    req = [canonical(x) for x in analysis.required_skills]
    pref = [canonical(x) for x in analysis.preferred_skills]
    matched = [x for x in req + pref if x in known]
    missing = [x for x in req if x not in known]
    weak = [x for x in req + pref if x in evidenced and x not in declared]
    unknown: set[str] = set()

    # skills
    if req or pref:
        r_ratio = (sum(1 for x in req if x in known) / len(req)) if req else 1.0
        p_ratio = (sum(1 for x in pref if x in known) / len(pref)) if pref else 1.0
        skill = 100 * (0.8 * r_ratio + 0.2 * p_ratio) if req else 100 * (0.5 + 0.5 * p_ratio)
        skill -= 3 * len(weak)  # weak evidence penalty
        skill = max(0.0, skill)
    else:
        skill, _ = 50.0, unknown.add("skills")

    # experience
    uy, jy = b.profile.years_experience, analysis.min_years_experience
    if jy is None:
        exp = 70.0
        unknown.add("job_experience")
    elif uy is None:
        exp = 50.0
        unknown.add("user_experience")
    else:
        exp = 100.0 if uy >= jy else 100.0 * (uy / jy) if jy else 100.0

    # semantic similarity (embeddings) + title overlap -> role
    emb_p, changed = ensure_embedding(provider, b.profile.embedding, b.embedding_text())
    if changed:
        b.profile.embedding = emb_p
    emb_j, _ = ensure_embedding(provider, job.embedding, f"{job.title}. {job.description}")
    sim = max(0.0, cosine(emb_p["v"], emb_j["v"]))
    targets = list(b.prefs.get("roles") or []) + ([b.profile.headline] if b.profile.headline else [])
    jt = set(_TOK.findall(job.title.lower()))
    overlap = max((len(jt & set(_TOK.findall(t.lower()))) / len(jt) for t in targets), default=0.0) if jt else 0.0
    if not targets:
        unknown.add("roles")
    role = 100 * (0.6 * overlap + 0.4 * min(1.0, sim * 2)) if targets else 100 * min(1.0, sim * 2)

    # education
    need = _EDU.get(analysis.education_level or "none", 0)
    have = _highest_edu(b)
    if analysis.education_level is None:
        edu = 80.0
        unknown.add("job_education")
    elif have is None:
        edu = 50.0
        unknown.add("user_education")
    else:
        edu = 100.0 if have >= need else 40.0

    # location
    ul = (b.profile.location or "").lower()
    pl = [x.lower() for x in b.prefs.get("locations") or []]
    jl = (job.location or "").lower()
    if job.remote_type == "remote" and (not jl or "worldwide" in jl or "anywhere" in jl or not ul
                                       or ul.split(",")[-1].strip() in jl or any(p in jl for p in pl)):
        loc = 100.0
    elif job.remote_type == "remote":
        loc = 70.0  # remote but region-restricted
    elif not jl or (not ul and not pl):
        loc, _ = 60.0, unknown.add("location")
    else:
        loc = 100.0 if (ul and ul.split(",")[0].strip() in jl) or any(p in jl for p in pl) else 30.0

    # salary
    ms = b.prefs.get("min_salary")
    if job.salary_max is None or not ms:
        sal, _ = 60.0, unknown.add("salary")
    else:
        sal = 100.0 if job.salary_max >= ms else 40.0

    # other preferences
    pr = b.prefs.get("remote_type") or "any"
    pts, n = 0.0, 0
    if pr != "any":
        n += 1
        pts += 100 if job.remote_type == pr else 0 if job.remote_type != "unknown" else 50
    ets = [e.lower() for e in b.prefs.get("employment_types") or []]
    if ets and job.employment_type:
        n += 1
        pts += 100 if any(e in job.employment_type.lower() for e in ets) else 30
    pref_s = pts / n if n else 70.0
    if not n:
        unknown.add("preferences")

    overall = (s.w_skill * skill + s.w_experience * exp + s.w_role * role + s.w_education * edu
               + s.w_location * loc + s.w_salary * sal + s.w_preference * pref_s)
    overall = round(max(0.0, min(100.0, overall)), 1)
    confidence = round(1 - len(unknown) / 9, 2)
    rec = recommendation_for(overall, s)
    strengths = ([f"Matches {len(matched)} listed skill(s): {', '.join(matched[:8])}"] if matched else []) + \
                ([f"Meets experience requirement ({jy:g}+ yrs)"] if jy and uy and uy >= jy else [])
    risks = ([f"Missing required skill(s): {', '.join(missing[:8])}"] if missing else []) + \
            ([f"Requires {jy:g}+ years; profile shows {uy:g}"] if jy and uy is not None and uy < jy else []) + \
            (["Job description contains instruction-like text (ignored)"] if analysis.injection_suspected else []) + \
            ([f"Low confidence: unknown {', '.join(sorted(unknown))}"] if confidence < 0.6 else [])
    return dict(
        overall_score=overall, skill_score=round(skill, 1), experience_score=round(exp, 1),
        role_score=round(role, 1), education_score=round(edu, 1), location_score=round(loc, 1),
        salary_score=round(sal, 1), preference_score=round(pref_s, 1), semantic_similarity=round(sim, 3),
        confidence=confidence, matched_skills=matched, missing_skills=missing, weak_skills=weak,
        recommendation=rec,
        explanation={"strengths": strengths, "skill_gaps": missing, "risks": risks,
                     "why": (f"Recommended: {rec} fit ({overall}/100)." if rec != "Not Recommended"
                             else f"Not recommended ({overall}/100): " + ("; ".join(risks) or "low overall fit")),
                     "summary_source": "rules"})


def llm_explain(provider: LLMProvider, job: Job, result: dict) -> str | None:
    """Optional natural-language rationale. It restates the computed facts only; score is unchanged."""
    if not provider.available:
        return None
    try:
        facts = {k: result[k] for k in ("overall_score", "matched_skills", "missing_skills", "recommendation")}
        text = provider.generate_text(
            "You explain job-match results in 2-3 sentences using ONLY the provided facts. Do not add skills.",
            f"Job title: {job.title}\nFacts: {facts}")
        return text.strip()[:800]
    except Exception:
        return None


def upsert_match(db: Session, user_id: int, job: Job, analysis: JDAnalysis, b: ProfileBundle,
                 provider: LLMProvider, use_llm_text: bool = False) -> JobMatch:
    res = compute_match(job, analysis, b, provider)
    if use_llm_text and (t := llm_explain(provider, job, res)):
        res["explanation"]["llm_summary"] = t
    m = db.scalar(select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.job_id == job.id))
    if m:
        for k, v in res.items():
            setattr(m, k, v)
    else:
        m = JobMatch(user_id=user_id, job_id=job.id, **res)
        db.add(m)
    db.commit()
    return m


def analysis_of(job: Job) -> JDAnalysis:
    if job.analysis:
        return JDAnalysis.model_validate(job.analysis)
    return heuristic_analyze(job.title, job.description or "")
