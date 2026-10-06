import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user, get_llm
from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Resume, ResumeVersion, User
from app.db.session import get_db
from app.llm.provider import LLMProvider
from app.schemas import ParsedCV, ProfileIn
from app.services import cv_parser
from app.services.audit import audit
from app.services.pipelines import process_resume
from app.services.profile import bundle_to_dict, load_bundle, save_profile
from app.services.skills import canonical

router = APIRouter(prefix="/resumes", tags=["resumes"])


def _own(db: Session, user: User, rid: int) -> Resume:
    r = db.get(Resume, rid)
    if not r or r.user_id != user.id:
        raise NotFoundError("Resume not found")
    return r


def _latest(db: Session, rid: int) -> ResumeVersion | None:
    return db.scalar(select(ResumeVersion).where(ResumeVersion.resume_id == rid)
                     .order_by(ResumeVersion.version.desc()).limit(1))


def _out(r: Resume, v: ResumeVersion | None, detail: bool = False) -> dict:
    d = {"id": r.id, "filename": r.original_filename, "size_bytes": r.size_bytes,
         "created_at": r.created_at, "status": v.status if v else None, "error": v.error if v else None,
         "version": v.version if v else None, "parser": v.parser if v else None}
    if detail and v:
        d["structured"] = v.structured
    return d


@router.post("", status_code=202)
async def upload(request: Request, background: BackgroundTasks, file: UploadFile = File(...),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db),
                 llm: LLMProvider = Depends(get_llm)):
    s = get_settings()
    limit = s.file_size_limit_mb * 1024 * 1024
    content = await file.read(limit + 1)  # bounded read
    ext = cv_parser.validate_upload(file.filename or "", content, limit)
    digest = hashlib.sha256(content).hexdigest()
    dup = db.scalar(select(Resume).where(Resume.user_id == user.id, Resume.content_hash == digest))
    if dup:
        return {**_out(dup, _latest(db, dup.id)), "duplicate": True}
    stored = f"{uuid.uuid4().hex}.{ext}"  # internal name; user filename never touches the filesystem
    up = Path(s.upload_dir)
    up.mkdir(parents=True, exist_ok=True)
    (up / stored).write_bytes(content)
    r = Resume(user_id=user.id, original_filename=cv_parser.sanitize_filename(file.filename or "resume"),
               stored_name=stored, mime_type=cv_parser.ALLOWED_EXT[ext], size_bytes=len(content), content_hash=digest)
    db.add(r)
    db.flush()
    v = ResumeVersion(resume_id=r.id, version=1, status="pending")
    db.add(v)
    db.commit()
    audit(db, user.id, "cv_upload", client_ip(request), resume_id=r.id)
    background.add_task(process_resume, v.id, llm)
    return {**_out(r, v), "duplicate": False}


@router.get("")
def list_resumes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rs = db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.id.desc()))
    return [_out(r, _latest(db, r.id)) for r in rs]


@router.get("/{rid}")
def get_resume(rid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _own(db, user, rid)
    return _out(r, _latest(db, r.id), detail=True)


@router.post("/{rid}/reparse", status_code=202)
def reparse(rid: int, background: BackgroundTasks, user: User = Depends(get_current_user),
            db: Session = Depends(get_db), llm: LLMProvider = Depends(get_llm)):
    r = _own(db, user, rid)
    n = (db.scalar(select(func.max(ResumeVersion.version)).where(ResumeVersion.resume_id == r.id)) or 0) + 1
    v = ResumeVersion(resume_id=r.id, version=n, status="pending")
    db.add(v)
    db.commit()
    background.add_task(process_resume, v.id, llm)
    return _out(r, v)


@router.post("/{rid}/apply-to-profile")
def apply_to_profile(rid: int, request: Request, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Explicit user action: merge parsed CV facts into the profile. Existing user-entered values win."""
    r = _own(db, user, rid)
    v = _latest(db, r.id)
    if not v or v.status != "parsed":
        raise ConflictError("Resume has not been parsed successfully yet")
    cv = ParsedCV.model_validate({k: x for k, x in v.structured.items() if k != "injection_suspected"})
    cur = bundle_to_dict(load_bundle(db, user.id))
    skills = list(dict.fromkeys(cur["skills"] + [canonical(s) for s in cv.skills]))
    merged = ProfileIn(
        full_name=cur["full_name"] or cv.name, headline=cur["headline"] or cv.headline,
        location=cur["location"], summary=cur["summary"] or cv.summary,
        years_experience=cur["years_experience"] if cur["years_experience"] is not None else cv.years_experience,
        preferences=cur["preferences"] or {}, certifications=cur["certifications"] or cv.certifications,
        languages=cur["languages"] or cv.languages, skills=skills,
        experiences=cur["experiences"] or [e.model_dump() for e in cv.experience],
        education=cur["education"] or [e.model_dump() for e in cv.education],
        projects=cur["projects"] or [p.model_dump() for p in cv.projects])
    out = save_profile(db, user.id, merged)
    audit(db, user.id, "profile_update", client_ip(request), source="resume", resume_id=r.id)
    return bundle_to_dict(out)


@router.delete("/{rid}", status_code=204)
def delete_resume(rid: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _own(db, user, rid)
    (Path(get_settings().upload_dir) / r.stored_name).unlink(missing_ok=True)
    db.delete(r)
    db.commit()
    audit(db, user.id, "cv_delete", client_ip(request), resume_id=rid)
