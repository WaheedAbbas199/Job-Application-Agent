"""Background pipelines (run outside the request cycle). Each opens its own DB session.

Execution backend: FastAPI BackgroundTasks (in-process). The functions are plain callables with
primitive arguments so they can be moved to Celery/RQ without changing business logic.
"""
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.agents.graph import run_discovery
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger, log
from app.db import session as dbs
from app.db.models import AgentRun, Application, ResumeVersion, Resume
from app.llm.provider import LLMProvider
from app.services import cv_parser, tracker
from app.services.documents import generate_document
from app.services.profile import load_bundle
from app.sources.base import JobSource

logger = get_logger(__name__)


def process_resume(version_id: int, provider: LLMProvider) -> None:
    s = get_settings()
    with dbs.SessionLocal() as db:
        v = db.get(ResumeVersion, version_id)
        if not v:
            return
        try:
            r = db.get(Resume, v.resume_id)
            ext = r.original_filename.rsplit(".", 1)[-1].lower()
            content = (Path(s.upload_dir) / r.stored_name).read_bytes()
            text = cv_parser.extract_text(content, ext)
            parsed, parser, inj = cv_parser.parse_cv(text, provider, s.max_retries)
            v.raw_text, v.parser = text, parser
            v.structured = {**parsed.model_dump(), "injection_suspected": inj}
            v.status, v.error = "parsed", None
        except AppError as exc:
            v.status, v.error = "failed", exc.message
        except Exception:
            logger.exception("resume processing crashed")
            v.status, v.error = "failed", "Unexpected error while parsing"
        db.commit()


def process_discovery(run_id: int, provider: LLMProvider, sources: list[JobSource]) -> None:
    s = get_settings()
    with dbs.SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        run.status, run.start_time = "running", datetime.now(timezone.utc)
        db.commit()
        t0 = time.monotonic()
        p = run.result or {}
        try:
            state = run_discovery(db, provider, sources, s, run.user_id, run.id,
                                  p.get("query"), p.get("location"), p.get("limit", 30))
            run.status = state.get("status", "failed")
            run.error = "; ".join(state.get("errors", [])) or None
            run.result = {"stats": state.get("stats", {}), "warnings": state.get("warnings", []),
                          "steps": state.get("steps")}
        except Exception as exc:
            db.rollback()
            run = db.get(AgentRun, run_id)
            run.status, run.error = "failed", f"{type(exc).__name__}"
            log(logger, 40, "discovery crashed", run_id=run_id)
        run.end_time = datetime.now(timezone.utc)
        run.latency_ms = round((time.monotonic() - t0) * 1000, 1)
        db.commit()


def process_application_prep(app_id: int, provider: LLMProvider) -> None:
    with dbs.SessionLocal() as db:
        a = db.get(Application, app_id)
        try:
            b = load_bundle(db, a.user_id)
            for t in ("resume", "cover_letter", "recruiter_message"):
                generate_document(db, a, t, b, provider)
            tracker.change_status(db, a, "Ready for Review", meta={"auto": "documents generated"})
        except Exception as exc:
            db.rollback()
            a = db.get(Application, app_id)
            tracker.change_status(db, a, "Saved", meta={"prep_failed": getattr(exc, "message", "error")})
