import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user, get_job_sources, get_llm, require_admin
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import AgentError, AgentRun, User
from app.db.session import get_db
from app.llm.provider import LLMProvider
from app.schemas import DiscoverIn
from app.services.audit import audit
from app.services.pipelines import process_discovery
from app.sources.base import JobSource

router = APIRouter(prefix="/agents", tags=["agents"])


def run_dict(r: AgentRun) -> dict:
    return {"id": r.id, "trace_id": r.trace_id, "agent_name": r.agent_name, "workflow": r.workflow,
            "status": r.status, "start_time": r.start_time, "end_time": r.end_time,
            "latency_ms": r.latency_ms, "error": r.error, "result": r.result}


@router.post("/discover", status_code=202)
def discover(body: DiscoverIn, background: BackgroundTasks, request: Request, user: User = Depends(get_current_user),
             db: Session = Depends(get_db), llm: LLMProvider = Depends(get_llm),
             sources: list[JobSource] = Depends(get_job_sources)):
    active = db.scalar(select(AgentRun).where(AgentRun.user_id == user.id, AgentRun.status.in_(["queued", "running"])))
    if active:
        raise ConflictError("A discovery run is already in progress")
    run = AgentRun(trace_id=uuid.uuid4().hex, user_id=user.id, agent_name="job_discovery_agent",
                   workflow="discover_match", status="queued",
                   result={"query": body.query, "location": body.location, "limit": body.limit})
    db.add(run)
    db.commit()
    audit(db, user.id, "agent_run_started", client_ip(request), run_id=run.id)
    background.add_task(process_discovery, run.id, llm, sources)
    return run_dict(run)


@router.get("/runs")
def runs(limit: int = Query(20, ge=1, le=100), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [run_dict(r) for r in db.scalars(select(AgentRun).where(AgentRun.user_id == user.id)
                                            .order_by(AgentRun.id.desc()).limit(limit))]


@router.get("/runs/{rid}")
def run(rid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.get(AgentRun, rid)
    if not r or r.user_id != user.id:
        raise NotFoundError("Run not found")
    return run_dict(r)


@router.get("/admin/errors")
def admin_errors(limit: int = Query(50, ge=1, le=200), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AgentError).order_by(AgentError.id.desc()).limit(limit))
    return [{"id": e.id, "run_id": e.run_id, "node": e.node, "message": e.message, "created_at": e.created_at} for e in rows]
