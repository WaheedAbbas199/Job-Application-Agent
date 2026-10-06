from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user, get_llm
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.db.models import Document, User
from app.db.session import get_db
from app.llm.provider import LLMProvider
from app.schemas import ApproveIn, DocEditIn, RegenerateIn
from app.services import tracker
from app.services.audit import audit
from app.services.documents import generate_document, save_version, truthfulness_warnings
from app.services.profile import load_bundle

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc(db: Session, user: User, did: int) -> Document:
    d = db.get(Document, did)
    if not d or d.user_id != user.id:
        raise NotFoundError("Document not found")
    return d


def doc_dict(d: Document, warnings: list[str] | None = None) -> dict:
    return {"id": d.id, "application_id": d.application_id, "type": d.type, "version": d.version,
            "status": d.status, "generator": d.generator, "content": d.content, "created_at": d.created_at,
            "unsupported_skills": warnings or []}


@router.get("/application/{aid}")
def list_docs(aid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tracker.get_owned(db, user.id, aid)
    b = load_bundle(db, user.id)
    docs = db.scalars(select(Document).where(Document.application_id == aid).order_by(Document.type, Document.version.desc()))
    return [doc_dict(d, truthfulness_warnings(d.content, b) if d.type != "interview_answer" else []) for d in docs]


@router.post("/application/{aid}/regenerate", status_code=201)
def regenerate(aid: int, body: RegenerateIn, request: Request, user: User = Depends(get_current_user),
               db: Session = Depends(get_db), llm: LLMProvider = Depends(get_llm)):
    a = tracker.get_owned(db, user.id, aid)
    d = generate_document(db, a, body.type, load_bundle(db, user.id), llm)
    audit(db, user.id, "document_generation", client_ip(request), application_id=aid, type=body.type)
    return doc_dict(d)


@router.post("/application/{aid}/followup", status_code=201)
def followup(aid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
             llm: LLMProvider = Depends(get_llm)):
    """Drafts a follow-up message for the user to review. Nothing is ever sent automatically."""
    a = tracker.get_owned(db, user.id, aid)
    if a.status not in ("Applied", "Assessment", "Interview"):
        raise ConflictError("Follow-ups are for applications that have been submitted")
    return doc_dict(generate_document(db, a, "followup_message", load_bundle(db, user.id), llm))


@router.get("/{did}")
def get_doc(did: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = _doc(db, user, did)
    return doc_dict(d, truthfulness_warnings(d.content, load_bundle(db, user.id)))


@router.patch("/{did}", status_code=201)
def edit(did: int, body: DocEditIn, request: Request, user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    """Edits never overwrite: a new version (generator='user') is created."""
    d = _doc(db, user, did)
    a = tracker.get_owned(db, user.id, d.application_id)
    nd = save_version(db, a, d.type, body.content, "user")
    audit(db, user.id, "document_edit", client_ip(request), document_id=nd.id)
    return doc_dict(nd, truthfulness_warnings(nd.content, load_bundle(db, user.id)))


@router.post("/{did}/approve")
def approve(did: int, body: ApproveIn, request: Request, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    d = _doc(db, user, did)
    warns = truthfulness_warnings(d.content, load_bundle(db, user.id))
    if warns and not body.acknowledge_unsupported:
        raise ValidationAppError("Document mentions skills not in your profile: " + ", ".join(warns) +
                                 ". Remove them, add them to your profile if true, or acknowledge to proceed.")
    d.status = "approved"
    db.commit()
    audit(db, user.id, "document_approval", client_ip(request), document_id=did, acknowledged=bool(warns))
    return doc_dict(d, warns)


@router.post("/{did}/reject")
def reject(did: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = _doc(db, user, did)
    d.status = "rejected"
    db.commit()
    audit(db, user.id, "document_rejection", client_ip(request), document_id=did)
    return doc_dict(d)
