from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_llm
from app.core.exceptions import NotFoundError
from app.db.models import Job, JobMatch, User
from app.db.session import get_db
from app.llm.provider import LLMProvider
from app.services.jd_analyzer import analyze_job
from app.services.matching import analysis_of, upsert_match
from app.services.profile import load_bundle

router = APIRouter(prefix="/matches", tags=["matches"])


def match_dict(m: JobMatch) -> dict:
    cols = ("job_id", "overall_score", "skill_score", "experience_score", "role_score", "education_score",
            "location_score", "salary_score", "preference_score", "semantic_similarity", "confidence",
            "matched_skills", "missing_skills", "weak_skills", "recommendation", "explanation")
    return {c: getattr(m, c) for c in cols}


@router.get("")
def list_matches(min_score: float = Query(0, ge=0, le=100), recommendation: str | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.overall_score >= min_score)
    if recommendation:
        stmt = stmt.where(JobMatch.recommendation == recommendation)
    rows = db.scalars(stmt.order_by(JobMatch.overall_score.desc()).offset((page - 1) * page_size).limit(page_size))
    return [match_dict(m) for m in rows]


@router.get("/job/{job_id}")
def get_match(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job_id))
    if not m:
        raise NotFoundError("No match computed for this job yet")
    return match_dict(m)


@router.post("/job/{job_id}")
def compute(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
            llm: LLMProvider = Depends(get_llm)):
    j = db.get(Job, job_id)
    if not j:
        raise NotFoundError("Job not found")
    if not j.analysis:
        analyze_job(db, j, llm)
    return match_dict(upsert_match(db, user.id, j, analysis_of(j), load_bundle(db, user.id), llm, use_llm_text=True))
