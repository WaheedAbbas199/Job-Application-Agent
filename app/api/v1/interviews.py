from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Interview, Job, JobMatch, User
from app.db.session import get_db
from app.services import tracker
from app.services.interview import build_interview_prep
from app.services.profile import load_bundle

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.post("/application/{aid}", status_code=201)
def generate(aid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = tracker.get_owned(db, user.id, aid)
    if a.status not in ("Interview", "Assessment"):
        raise ConflictError("Interview preparation is available once the application reaches Assessment/Interview")
    job = db.get(Job, a.job_id)
    m = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == a.job_id))
    i = Interview(user_id=user.id, application_id=a.id, content=build_interview_prep(job, load_bundle(db, user.id), m))
    db.add(i)
    db.commit()
    return {"id": i.id, "application_id": a.id, "content": i.content, "created_at": i.created_at}


@router.get("/application/{aid}")
def latest(aid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tracker.get_owned(db, user.id, aid)
    i = db.scalar(select(Interview).where(Interview.application_id == aid).order_by(Interview.id.desc()).limit(1))
    if not i:
        raise NotFoundError("No interview preparation yet")
    return {"id": i.id, "application_id": aid, "content": i.content, "created_at": i.created_at}
