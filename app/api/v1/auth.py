from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user, get_token_payload
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import DUMMY_HASH, create_access_token, hash_password, verify_password
from app.db import models as m
from app.db.session import get_db
from app.schemas import DeleteAccountIn, LoginIn, RegisterIn, TokenOut, UserOut
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(m.User).where(m.User.email == email)):
        raise ConflictError("Email already registered")
    role = "admin" if email in get_settings().admin_list else "user"
    user = m.User(email=email, password_hash=hash_password(body.password), role=role)
    db.add(user)
    db.commit()
    audit(db, user.id, "register", client_ip(request))
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower()))
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)  # constant-ish time
    if not user or not ok or not user.is_active:
        audit(db, user.id if user else None, "login_failed", client_ip(request))
        raise AuthenticationError("Invalid email or password")
    token, _ = create_access_token(user.id, user.role)
    audit(db, user.id, "login", client_ip(request))
    return TokenOut(access_token=token)


@router.post("/logout", status_code=204)
def logout(request: Request, payload: dict = Depends(get_token_payload), user: m.User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    db.add(m.RevokedToken(jti=payload["jti"], revoked_at=datetime.now(timezone.utc)))
    db.commit()
    audit(db, user.id, "logout", client_ip(request))


@router.get("/me", response_model=UserOut)
def me(user: m.User = Depends(get_current_user)):
    return user


@router.delete("/me", status_code=204)
def delete_account(body: DeleteAccountIn, request: Request, user: m.User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Right to erasure: removes the account, CV files and all user-owned rows. Audit rows are kept (no PII)."""
    if not verify_password(body.password, user.password_hash):
        raise AuthenticationError("Invalid password")
    uid = user.id
    upload = Path(get_settings().upload_dir)
    for r in db.scalars(select(m.Resume).where(m.Resume.user_id == uid)):
        (upload / r.stored_name).unlink(missing_ok=True)
    db.execute(delete(m.User).where(m.User.id == uid))  # ON DELETE CASCADE removes the rest
    db.commit()
    audit(db, None, "account_deleted", client_ip(request), former_user_id=uid)
