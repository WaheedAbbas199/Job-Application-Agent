"""Profile persistence + a read-only bundle used by matching and document generation."""
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Education, Experience, Project, UserProfile, UserSkill
from app.schemas import ProfileIn
from app.services.skills import canonical, extract_skills


@dataclass
class ProfileBundle:
    user_id: int
    profile: UserProfile | None
    skills: list[str] = field(default_factory=list)
    experiences: list[Experience] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)

    @property
    def prefs(self) -> dict:
        return (self.profile.preferences if self.profile else None) or {}

    @property
    def declared(self) -> set[str]:
        return {canonical(s) for s in self.skills}

    @property
    def evidenced(self) -> set[str]:
        """Skills the user demonstrably used (experience/project text) even if not declared."""
        text = " ".join([(e.description or "") + " " + e.title for e in self.experiences]
                        + [(p.description or "") + " " + " ".join(p.technologies or []) for p in self.projects])
        return set(extract_skills(text))

    def embedding_text(self) -> str:
        p = self.profile
        parts = [p.headline or "" if p else "", p.summary or "" if p else "", " ".join(self.skills)]
        parts += [e.title for e in self.experiences] + [x.name for x in self.projects]
        return " . ".join(x for x in parts if x)


def load_bundle(db: Session, user_id: int) -> ProfileBundle:
    g = lambda m: list(db.scalars(select(m).where(m.user_id == user_id).order_by(m.id)))
    prof = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    return ProfileBundle(user_id, prof, [s.name for s in g(UserSkill)], g(Experience), g(Education), g(Project))


def save_profile(db: Session, user_id: int, data: ProfileIn) -> ProfileBundle:
    prof = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if not prof:
        prof = UserProfile(user_id=user_id)
        db.add(prof)
    for f in ("full_name", "headline", "location", "summary", "years_experience", "certifications", "languages"):
        setattr(prof, f, getattr(data, f))
    prof.preferences = data.preferences.model_dump()
    prof.embedding = None  # invalidate cached embedding
    for m in (UserSkill, Experience, Education, Project):
        db.execute(delete(m).where(m.user_id == user_id))
    db.add_all([UserSkill(user_id=user_id, name=s) for s in data.skills])
    db.add_all([Experience(user_id=user_id, **e.model_dump()) for e in data.experiences])
    db.add_all([Education(user_id=user_id, **e.model_dump()) for e in data.education])
    db.add_all([Project(user_id=user_id, **p.model_dump()) for p in data.projects])
    db.commit()
    return load_bundle(db, user_id)


def bundle_to_dict(b: ProfileBundle) -> dict:
    p = b.profile
    return {
        "full_name": p.full_name if p else None, "headline": p.headline if p else None,
        "location": p.location if p else None, "summary": p.summary if p else None,
        "years_experience": p.years_experience if p else None,
        "preferences": b.prefs, "certifications": (p.certifications if p else []) or [],
        "languages": (p.languages if p else []) or [], "skills": b.skills,
        "experiences": [{"title": e.title, "company": e.company, "start": e.start, "end": e.end,
                         "description": e.description} for e in b.experiences],
        "education": [{"degree": e.degree, "institution": e.institution, "year": e.year} for e in b.education],
        "projects": [{"name": x.name, "description": x.description, "technologies": x.technologies}
                     for x in b.projects],
    }
