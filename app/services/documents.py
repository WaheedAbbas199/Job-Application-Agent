"""Tailored documents. TRUTHFULNESS: content is composed only from stored profile facts.

Tailoring = reorder + highlight existing facts. Missing skills are never added. LLM text (cover letter,
messages) is validated: any skill mentioned that is not in the profile causes rejection -> safe template.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import DocumentGenerationError
from app.db.models import Application, Document, Job, JobMatch
from app.llm.provider import LLMProvider
from app.llm.safety import SYSTEM_GUARD, wrap_untrusted
from app.services.profile import ProfileBundle
from app.services.skills import canonical, unsupported_skills


def _allowed(b: ProfileBundle) -> set[str]:
    return b.declared | b.evidenced


def _ordered_skills(b: ProfileBundle, matched: list[str]) -> list[str]:
    m = {canonical(x) for x in matched}
    return sorted(b.skills, key=lambda s: (canonical(s) not in m, s.lower()))


def build_resume(b: ProfileBundle, match: JobMatch | None) -> str:
    p = b.profile
    matched = (match.matched_skills if match else []) or []
    lines = [f"# {p.full_name or 'Candidate'}"]
    if p.headline:
        lines.append(f"**{p.headline}**")
    if p.location:
        lines.append(p.location)
    if p.summary:
        lines += ["", "## Summary", p.summary]
    if b.skills:
        lines += ["", "## Skills", ", ".join(_ordered_skills(b, matched))]
    if b.experiences:
        lines += ["", "## Experience"]
        for e in b.experiences:
            dates = f" ({e.start or '?'} - {e.end or '?'})" if e.start or e.end else ""
            lines.append(f"### {e.title}{' — ' + e.company if e.company else ''}{dates}")
            if e.description:
                lines.append(e.description)
    if b.projects:
        m = {canonical(x) for x in matched}
        projs = sorted(b.projects, key=lambda x: -sum(canonical(t) in m for t in (x.technologies or [])))
        lines += ["", "## Projects"]
        for x in projs:
            lines.append(f"### {x.name}")
            if x.description:
                lines.append(x.description)
            if x.technologies:
                lines.append("Technologies: " + ", ".join(x.technologies))
    if b.education:
        lines += ["", "## Education"]
        lines += [f"- {e.degree}{', ' + e.institution if e.institution else ''}{' (' + e.year + ')' if e.year else ''}"
                  for e in b.education]
    if p.certifications:
        lines += ["", "## Certifications"] + [f"- {c}" for c in p.certifications]
    if p.languages:
        lines += ["", "## Languages", ", ".join(p.languages)]
    return "\n".join(lines)


def _template_cover(b: ProfileBundle, job: Job, match: JobMatch | None) -> str:
    p = b.profile
    matched = ((match.matched_skills if match else []) or [])[:6]
    para = f"I am writing to apply for the {job.title} position at {job.company}."
    if p.headline:
        para += f" I am a {p.headline}."
    skills = f" My background includes {', '.join(matched)}." if matched else ""
    yrs = f" I bring {p.years_experience:g} years of experience." if p.years_experience else ""
    proj = f" Recent work includes {b.projects[0].name}." if b.projects else ""
    return (f"Dear Hiring Team at {job.company},\n\n{para}{yrs}{skills}{proj}\n\n"
            f"I would welcome the chance to discuss how my experience fits this role.\n\n"
            f"Kind regards,\n{p.full_name or ''}").strip()


def _template_recruiter(b: ProfileBundle, job: Job, match: JobMatch | None) -> str:
    matched = ((match.matched_skills if match else []) or [])[:4]
    s = f" with experience in {', '.join(matched)}" if matched else ""
    return (f"Hi, I'm {b.profile.full_name or 'a candidate'}{s}. I'm interested in the {job.title} role at "
            f"{job.company} and would love to connect about it. Thank you!")


def _template_followup(b: ProfileBundle, job: Job) -> str:
    return (f"Hello, I applied for the {job.title} role at {job.company} and wanted to follow up on the status "
            f"of my application. I remain very interested. Thank you for your time.\n\n{b.profile.full_name or ''}").strip()


def _llm_text(provider: LLMProvider, kind: str, b: ProfileBundle, job: Job, match: JobMatch | None,
              fallback: str) -> tuple[str, str]:
    if not provider.available:
        return fallback, "template"
    facts = {"name": b.profile.full_name, "headline": b.profile.headline, "years": b.profile.years_experience,
             "skills_to_mention": ((match.matched_skills if match else []) or [])[:8],
             "projects": [x.name for x in b.projects[:3]]}
    try:
        text = provider.generate_text(
            SYSTEM_GUARD + f" Write a concise, honest {kind}. Use ONLY the candidate facts given. "
            "Do not mention any technology that is not in skills_to_mention.",
            f"Candidate facts: {facts}\nJob: {job.title} at {job.company}\n{wrap_untrusted(job.description or '', 4000)}")
        text = text.strip()
        if not text or unsupported_skills(text, _allowed(b)):
            return fallback, "template"  # guardrail rejected hallucinated skills
        return text, "llm"
    except Exception:
        return fallback, "template"


def generate_document(db: Session, app: Application, doc_type: str, b: ProfileBundle,
                      provider: LLMProvider) -> Document:
    if not b.profile:
        raise DocumentGenerationError("Complete your profile before generating documents.")
    job = db.get(Job, app.job_id)
    match = db.scalar(select(JobMatch).where(JobMatch.user_id == app.user_id, JobMatch.job_id == app.job_id))
    gen = "template"
    if doc_type == "resume":
        content = build_resume(b, match)
    elif doc_type == "cover_letter":
        content, gen = _llm_text(provider, "cover letter", b, job, match, _template_cover(b, job, match))
    elif doc_type == "recruiter_message":
        content, gen = _llm_text(provider, "recruiter message", b, job, match, _template_recruiter(b, job, match))
    elif doc_type == "followup_message":
        content = _template_followup(b, job)
    else:
        raise DocumentGenerationError("Unsupported document type.")
    return save_version(db, app, doc_type, content, gen)


def save_version(db: Session, app: Application, doc_type: str, content: str, generator: str) -> Document:
    nxt = (db.scalar(select(func.max(Document.version)).where(
        Document.application_id == app.id, Document.type == doc_type)) or 0) + 1
    d = Document(user_id=app.user_id, application_id=app.id, version=nxt, type=doc_type,
                 content=content, generator=generator, status="draft")
    db.add(d)
    db.commit()
    return d


def truthfulness_warnings(content: str, b: ProfileBundle) -> list[str]:
    return unsupported_skills(content, _allowed(b))
