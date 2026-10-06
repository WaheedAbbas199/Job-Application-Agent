from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user, get_llm
from app.core.exceptions import ConflictError
from app.db.models import Application, ApplicationEvent, Document, Job, JobMatch, User
from app.db.session import get_db
from app.llm.provider import LLMProvider
from app.schemas import ApplicationPatch, ApplyIn, CreateApplicationIn, StatusIn
from app.services import tracker
from app.services.audit import audit
from app.services.pipelines import process_application_prep

router = APIRouter(prefix="/applications", tags=["applications"])


def app_dict(a: Application, job: Job | None, match: JobMatch | None = None) -> dict:
    return {"id": a.id, "job_id": a.job_id, "status": a.status, "notes": a.notes, "version": a.version_id,
            "follow_up_date": a.follow_up_date, "created_at": a.created_at, "updated_at": a.updated_at,
            "job": None if not job else {"title": job.title, "company": job.company, "location": job.location,
                                          "application_url": job.application_url},
            "match_score": match.overall_score if match else None}


@router.post("", status_code=201)
def create(body: CreateApplicationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = tracker.create_application(db, user.id, body.job_id)
    audit(db, user.id, "application_create", application_id=a.id)
    return app_dict(a, db.get(Job, a.job_id))


@router.get("")
def list_apps(status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Application).where(Application.user_id == user.id)
    if status:
        stmt = stmt.where(Application.status == status)
    apps = db.scalars(stmt.order_by(Application.updated_at.desc()).offset((page - 1) * page_size).limit(page_size))
    out = []
    for a in apps:
        m = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == a.job_id))
        out.append(app_dict(a, db.get(Job, a.job_id), m))
    return out


@router.get("/{aid}")
def detail(aid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = tracker.get_owned(db, user.id, aid)
    m = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == a.job_id))
    events = db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == a.id)
                        .order_by(ApplicationEvent.id))
    docs = db.scalars(select(Document).where(Document.application_id == a.id).order_by(Document.type, Document.version))
    d = app_dict(a, db.get(Job, a.job_id), m)
    d["events"] = [{"old_status": e.old_status, "new_status": e.new_status, "timestamp": e.timestamp,
                    "meta": e.meta} for e in events]
    d["documents"] = [{"id": x.id, "type": x.type, "version": x.version, "status": x.status,
                       "generator": x.generator, "created_at": x.created_at} for x in docs]
    return d


@router.patch("/{aid}")
def patch(aid: int, body: ApplicationPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = tracker.get_owned(db, user.id, aid)
    if body.notes is not None:
        a.notes = body.notes
    if body.follow_up_date is not None:
        a.follow_up_date = body.follow_up_date
    db.commit()
    return app_dict(a, db.get(Job, a.job_id))


@router.post("/{aid}/status")
def set_status(aid: int, body: StatusIn, request: Request, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    a = tracker.get_owned(db, user.id, aid)
    if body.status == "Applied":
        raise ConflictError("Use POST /applications/{id}/apply (requires approved documents and confirmation)")
    old = a.status
    a = tracker.change_status(db, a, body.status, body.expected_version, body.note)
    audit(db, user.id, "application_status_change", client_ip(request), application_id=aid, old=old, new=body.status)
    return app_dict(a, db.get(Job, a.job_id))


@router.post("/{aid}/prepare", status_code=202)
def prepare(aid: int, background: BackgroundTasks, request: Request, user: User = Depends(get_current_user),
            db: Session = Depends(get_db), llm: LLMProvider = Depends(get_llm)):
    a = tracker.get_owned(db, user.id, aid)
    if a.status == "Preparing":
        raise ConflictError("Preparation already in progress")
    tracker.change_status(db, a, "Preparing")
    audit(db, user.id, "document_generation", client_ip(request), application_id=aid)
    background.add_task(process_application_prep, a.id, llm)
    return {"application_id": a.id, "status": "Preparing"}


@router.post("/{aid}/apply")
def apply(aid: int, body: ApplyIn, request: Request, user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    a = tracker.get_owned(db, user.id, aid)
    a = tracker.apply_confirmed(db, a, body.confirm)
    job = db.get(Job, a.job_id)
    audit(db, user.id, "application_submission", client_ip(request), application_id=aid)
    return {**app_dict(a, job), "next_step": "Automated submission is not configured. Use the application URL to "
            "submit your approved documents yourself.", "application_url": job.application_url}
