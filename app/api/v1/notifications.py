from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.exceptions import NotFoundError
from app.db.models import Notification, User
from app.db.session import get_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(unread_only: bool = False, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Follow-up reminders only appear once due (reminders, never automatic sends)."""
    now = datetime.now(timezone.utc)
    stmt = select(Notification).where(Notification.user_id == user.id,
                                      or_(Notification.due_at.is_(None), Notification.due_at <= now))
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    return [{"id": n.id, "type": n.type, "message": n.message, "application_id": n.application_id,
             "due_at": n.due_at, "read": n.read, "created_at": n.created_at}
            for n in db.scalars(stmt.order_by(Notification.id.desc()).limit(100))]


@router.post("/{nid}/read", status_code=204)
def mark_read(nid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id:
        raise NotFoundError("Notification not found")
    n.read = True
    db.commit()
