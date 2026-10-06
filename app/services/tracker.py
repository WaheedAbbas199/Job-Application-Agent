"""Application tracking: status machine with immutable event history + follow-up reminders."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import get_settings
from app.core.exceptions import ApplicationError, ConflictError, NotFoundError
from app.db.models import Application, ApplicationEvent, Document, Job, Notification
from app.domain import APPLICATION_STATUSES


def get_owned(db: Session, user_id: int, app_id: int) -> Application:
    a = db.get(Application, app_id)
    if not a or a.user_id != user_id:  # 404 (not 403) so ids are not enumerable
        raise NotFoundError("Application not found")
    return a


def create_application(db: Session, user_id: int, job_id: int, status: str = "Saved") -> Application:
    if not db.get(Job, job_id):
        raise NotFoundError("Job not found")
    existing = db.scalar(select(Application).where(Application.user_id == user_id, Application.job_id == job_id))
    if existing:
        raise ConflictError("An application for this job already exists")
    a = Application(user_id=user_id, job_id=job_id, status=status)
    db.add(a)
    try:
        db.flush()
        db.add(ApplicationEvent(application_id=a.id, old_status=None, new_status=status, meta={"created": True}))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("An application for this job already exists") from exc
    return a


def change_status(db: Session, a: Application, new: str, expected_version: int | None = None,
                  note: str | None = None, meta: dict | None = None) -> Application:
    if new not in APPLICATION_STATUSES:
        raise ApplicationError(f"Unknown status '{new}'")
    if expected_version is not None and expected_version != a.version_id:
        raise ConflictError("Application was modified elsewhere; reload and retry")
    old = a.status
    if old == new:
        return a
    a.status = new
    db.add(ApplicationEvent(application_id=a.id, old_status=old, new_status=new,
                            meta={**(meta or {}), **({"note": note} if note else {})}))
    if new == "Applied":
        due = datetime.now(timezone.utc) + timedelta(days=get_settings().followup_days)
        a.follow_up_date = a.follow_up_date or due
        job = db.get(Job, a.job_id)
        db.add(Notification(user_id=a.user_id, application_id=a.id, type="follow_up", due_at=a.follow_up_date,
                            message=f"Follow up on your application: {job.title} at {job.company}"))
    try:
        db.commit()
    except StaleDataError as exc:
        db.rollback()
        raise ConflictError("Concurrent update detected; reload and retry") from exc
    return a


def apply_confirmed(db: Session, a: Application, confirm: bool) -> Application:
    """Marks the application as applied after EXPLICIT user confirmation and at least one approved document.
    The system never submits to external sites by itself (integration not configured)."""
    if not confirm:
        raise ApplicationError("Explicit confirmation required (confirm=true)")
    approved = db.scalar(select(Document.id).where(Document.application_id == a.id, Document.status == "approved"))
    if not approved:
        raise ApplicationError("Approve at least one document before applying")
    if a.status == "Applied":
        raise ConflictError("Already marked as applied")
    return change_status(db, a, "Applied", meta={"approved_by_user": True})
