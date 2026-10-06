from sqlalchemy.orm import Session

from app.db.models import AuditLog


def audit(db: Session, user_id: int | None, action: str, ip: str | None = None, **details) -> None:
    """Record a security-relevant event. Never put CV content or secrets in details."""
    db.add(AuditLog(user_id=user_id, action=action, details=details, ip=ip))
    db.commit()
