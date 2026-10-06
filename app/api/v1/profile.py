from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas import ProfileIn
from app.services.audit import audit
from app.services.profile import bundle_to_dict, load_bundle, save_profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return bundle_to_dict(load_bundle(db, user.id))


@router.put("")
def put_profile(body: ProfileIn, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    b = save_profile(db, user.id, body)
    audit(db, user.id, "profile_update", client_ip(request))
    return bundle_to_dict(b)
