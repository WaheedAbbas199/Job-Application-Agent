"""Job-description analysis: deterministic extraction, optionally refined by the LLM (validated)."""
import re

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Job, JobSkill
from app.llm.provider import LLMProvider
from app.llm.safety import SYSTEM_GUARD, detect_injection, strip_injection_lines, wrap_untrusted
from app.llm.structured import structured_call
from app.schemas import JDAnalysis
from app.services.embeddings import ensure_embedding
from app.services.skills import extract_skills

_PREF = re.compile(r"nice to have|preferred|bonus|a plus|\bplus\b|desirable|advantage|optional", re.I)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d+\s*)?(?:years|yrs)", re.I)
_BULLET = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+")
_SENIORITY = [("intern", "intern"), ("junior", "junior"), ("entry", "junior"), ("senior", "senior"),
              ("staff", "senior"), ("principal", "senior"), ("lead", "lead"), ("manager", "lead"),
              ("mid", "mid")]


def heuristic_analyze(title: str, description: str) -> JDAnalysis:
    flagged = detect_injection(description)
    description = strip_injection_lines(description)
    required, preferred = [], []
    lines = [l.strip() for l in description.split("\n") if l.strip()]
    in_pref = False
    for line in lines:
        if len(line) < 60 and line.endswith(":") or (len(line) < 40 and line.istitle()):
            in_pref = bool(_PREF.search(line))
        is_pref = in_pref or bool(_PREF.search(line))
        for s in extract_skills(line):
            (preferred if is_pref else required).append(s)
    required = list(dict.fromkeys(required))
    preferred = [s for s in dict.fromkeys(preferred) if s not in required]
    years = [int(m.group(1)) for m in _YEARS.finditer(description) if int(m.group(1)) <= 20]
    low = description.lower()
    edu = "phd" if re.search(r"\bph\.?d\b|doctorate", low) else "master" if re.search(
        r"master'?s|\bmsc\b|\bm\.s\.", low) else "bachelor" if re.search(
        r"bachelor|\bbsc\b|\bb\.s\.|degree in", low) else None
    tl = title.lower()
    seniority = next((v for k, v in _SENIORITY if k in tl), None)
    bullets = [_BULLET.sub("", l) for l in lines if _BULLET.match(l)]
    reqs = [b for b in bullets if re.search(r"experience|proficien|knowledge|degree|ability|skills", b, re.I)]
    resp = [b for b in bullets if b not in reqs]
    return JDAnalysis(
        required_skills=required, preferred_skills=preferred,
        min_years_experience=float(min(years)) if years else None, education_level=edu,
        responsibilities=resp[:15], requirements=reqs[:15], seniority=seniority,
        keywords=extract_skills(title + " " + description)[:20], injection_suspected=flagged)


def analyze_text(title: str, description: str, provider: LLMProvider) -> JDAnalysis:
    base = heuristic_analyze(title, description)
    if provider.available:
        try:
            prompt = (f"Return JSON matching: {JDAnalysis.model_json_schema()}\n"
                      f"Title: {title}\n{wrap_untrusted(description)}")
            llm = structured_call(provider, SYSTEM_GUARD + " Extract job requirements.", prompt,
                                  JDAnalysis, get_settings().max_retries)
            low = description.lower()  # ground: only skills that literally appear
            llm.required_skills = [s for s in llm.required_skills if s.lower() in low]
            llm.preferred_skills = [s for s in llm.preferred_skills if s.lower() in low and s not in llm.required_skills]
            llm.injection_suspected = base.injection_suspected
            return llm
        except Exception:
            pass
    return base


def analyze_job(db: Session, job: Job, provider: LLMProvider) -> JDAnalysis:
    a = analyze_text(job.title, job.description or "", provider)
    job.analysis = a.model_dump()
    job.requirements, job.responsibilities = a.requirements, a.responsibilities
    job.experience_level = a.seniority
    db.execute(delete(JobSkill).where(JobSkill.job_id == job.id))
    db.add_all([JobSkill(job_id=job.id, name=s, required=True) for s in a.required_skills]
               + [JobSkill(job_id=job.id, name=s, required=False) for s in a.preferred_skills])
    job.embedding, _ = ensure_embedding(provider, job.embedding, f"{job.title}. {job.description}")
    db.commit()
    return a
