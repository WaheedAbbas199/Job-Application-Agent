from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_llm
from app.core.exceptions import NotFoundError
from app.db.models import Job, JobMatch, User
from app.db.session import get_db
from app.llm.provider import LLMProvider
from app.services import tracker
from app.services.jd_analyzer import analyze_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


def job_dict(j: Job, m: JobMatch | None = None, detail: bool = False) -> dict:
    d = {"id": j.id, "title": j.title, "company": j.company, "location": j.location, "remote_type": j.remote_type,
         "employment_type": j.employment_type, "salary_min": j.salary_min, "salary_max": j.salary_max,
         "salary_currency": j.salary_currency, "posted_at": j.posted_at, "source": j.source,
         "application_url": j.application_url,
         "match": None if not m else {"overall_score": m.overall_score, "recommendation": m.recommendation,
                                      "matched_skills": m.matched_skills, "missing_skills": m.missing_skills}}
    if detail:
        d.update(description=j.description, analysis=j.analysis, experience_level=j.experience_level)
    return d


@router.get("")
def list_jobs(q: str | None = None, remote_type: str | None = None, sort: str = "match",
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Only jobs the user has been matched with (their discovery results) - paginated."""
    stmt = (select(Job, JobMatch).join(JobMatch, (JobMatch.job_id == Job.id) & (JobMatch.user_id == user.id)))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Job.title).like(like), func.lower(Job.company).like(like)))
    if remote_type:
        stmt = stmt.where(Job.remote_type == remote_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(JobMatch.overall_score.desc() if sort == "match" else Job.created_at.desc())
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [job_dict(j, m) for j, m in rows]}


def _job(db: Session, jid: int) -> Job:
    j = db.get(Job, jid)
    if not j:
        raise NotFoundError("Job not found")
    return j


@router.get("/{jid}")
def get_job(jid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    j = _job(db, jid)
    m = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == jid))
    return job_dict(j, m, detail=True)


@router.post("/{jid}/analyze")
def analyze(jid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
            llm: LLMProvider = Depends(get_llm)):
    j = _job(db, jid)
    analyze_job(db, j, llm)
    return job_dict(j, None, detail=True)


@router.post("/{jid}/save", status_code=201)
def save_job(jid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _job(db, jid)
    a = tracker.create_application(db, user.id, jid, "Saved")
    return {"application_id": a.id, "status": a.status}
