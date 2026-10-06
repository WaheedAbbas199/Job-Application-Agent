from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_token
from app.db.models import RevokedToken, User
from app.db.session import get_db
from app.llm.provider import LLMProvider, get_llm  # noqa: F401  (re-exported for overrides)
from app.sources.api_sources import default_sources
from app.sources.base import JobSource

bearer = HTTPBearer(auto_error=False)


def get_job_sources() -> list[JobSource]:
    return default_sources()


def get_token_payload(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not cred:
        raise AuthenticationError("Not authenticated")
    return decode_token(cred.credentials)


def get_current_user(payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)) -> User:
    if db.get(RevokedToken, payload.get("jti")):
        raise AuthenticationError("Token revoked")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise AuthenticationError("Invalid user")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise AuthorizationError("Admin only")
    return user


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
