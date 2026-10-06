from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return analytics.overview(db, user.id)


@router.get("/strategy")
def strategy(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return analytics.strategy(db, user.id)
