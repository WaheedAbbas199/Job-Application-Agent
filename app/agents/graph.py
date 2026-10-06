"""LangGraph discovery workflow with explicit state and hard loop-safety.

START -> load_profile -> discover -> persist(normalize+dedup) -> filter -> analyze -> match -> recommend -> END
Every node: validates state, does one job, returns state updates, logs, records errors.
Safety: max_agent_steps, wall-clock timeout, bounded transient retries. The graph has no cycles.
Human review/approval happens outside the graph (API), by design.
"""
import time
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, IntegrationNotConfigured, JobSourceError, MatchingError
from app.core.logging import get_logger, log
from app.core.retry import with_retry
from app.db.models import AgentError, Job, Notification
from app.llm.provider import LLMProvider
from app.services.ingest import upsert_job
from app.services.jd_analyzer import analyze_job
from app.services.matching import analysis_of, upsert_match
from app.services.profile import load_bundle
from app.sources.base import JobSource

logger = get_logger(__name__)
FAILED = ("failed", "aborted")


class AgentState(TypedDict, total=False):
    user_id: int
    run_id: int
    query: str | None
    location: str | None
    limit: int
    raw_jobs: list
    job_ids: list[int]
    kept_ids: list[int]
    match_count: int
    steps: int
    deadline: float
    errors: list[str]
    warnings: list[str]
    status: str
    stats: dict


def build_graph(db: Session, provider: LLMProvider, sources: list[JobSource], settings: Settings,
                sleep: Callable[[float], None] = time.sleep):
    def node(name: str, fn: Callable[[AgentState], dict]):
        def wrapped(state: AgentState) -> dict:
            if state.get("status") in FAILED:
                return {}
            steps = state.get("steps", 0) + 1
            if steps > settings.max_agent_steps:
                return {"status": "aborted", "errors": state.get("errors", []) + ["max_agent_steps exceeded"]}
            if time.monotonic() > state["deadline"]:
                return {"status": "aborted", "errors": state.get("errors", []) + [f"timeout in {name}"]}
            t0 = time.monotonic()
            try:
                out = with_retry(lambda: fn(state), max_retries=settings.max_retries, sleep=sleep)
            except Exception as exc:  # recorded, never swallowed silently
                db.rollback()
                msg = exc.message if isinstance(exc, AppError) else "internal error"
                db.add(AgentError(run_id=state["run_id"], node=name, message=f"{type(exc).__name__}: {msg}"))
                db.commit()
                log(logger, 40, "agent node failed", node=name, run_id=state["run_id"], error=msg)
                return {"status": "failed", "steps": steps, "errors": state.get("errors", []) + [f"{name}: {msg}"]}
            log(logger, 20, "agent node ok", node=name, run_id=state["run_id"],
                latency_ms=round((time.monotonic() - t0) * 1000, 1))
            out["steps"] = steps
            return out
        return wrapped

    def load_profile(s: AgentState) -> dict:
        b = load_bundle(db, s["user_id"])
        if not b.profile:
            raise MatchingError("Complete your profile before running discovery.")
        q = s.get("query") or next(iter(b.prefs.get("roles") or []), None) or b.profile.headline
        return {"query": q, "stats": {}}

    def discover(s: AgentState) -> dict:
        if not sources:
            raise IntegrationNotConfigured("No job sources configured")
        raw, warns = [], list(s.get("warnings", []))
        for src in sources:
            try:
                raw += with_retry(lambda: src.fetch(s.get("query"), s.get("location"), s["limit"]),
                                  max_retries=settings.max_retries, sleep=sleep)
            except JobSourceError as exc:  # graceful degradation: other sources still count
                warns.append(f"{src.name}: {exc.message}")
        if not raw and warns:
            raise JobSourceError("All job sources failed: " + "; ".join(warns))
        return {"raw_jobs": raw[: settings.job_fetch_limit * 2], "warnings": warns}

    def persist(s: AgentState) -> dict:
        ids, new = [], 0
        for r in s.get("raw_jobs", []):
            job, created = upsert_job(db, r)
            new += created
            if job.id not in ids:
                ids.append(job.id)
        return {"job_ids": ids, "raw_jobs": [], "stats": {**s["stats"], "fetched": len(ids), "new": new,
                                                          "duplicates_skipped": len(s.get("raw_jobs", [])) - new}}

    def filter_(s: AgentState) -> dict:
        b = load_bundle(db, s["user_id"])
        want, min_sal = b.prefs.get("remote_type"), b.prefs.get("min_salary")
        kept = []
        for jid in s.get("job_ids", []):
            j = db.get(Job, jid)
            if want == "remote" and j.remote_type == "onsite":
                continue
            if min_sal and j.salary_max and j.salary_max < min_sal:
                continue
            kept.append(jid)
        return {"kept_ids": kept, "stats": {**s["stats"], "kept_after_filter": len(kept)}}

    def analyze(s: AgentState) -> dict:
        n = 0
        for jid in s.get("kept_ids", []):
            j = db.get(Job, jid)
            if not j.analysis:
                analyze_job(db, j, provider)
                n += 1
        return {"stats": {**s["stats"], "analyzed": n}}

    def match(s: AgentState) -> dict:
        b = load_bundle(db, s["user_id"])
        cnt = 0
        for jid in s.get("kept_ids", []):
            j = db.get(Job, jid)
            upsert_match(db, s["user_id"], j, analysis_of(j), b, provider)
            cnt += 1
        if b.profile.embedding is not None:
            db.commit()
        return {"match_count": cnt, "stats": {**s["stats"], "matched": cnt}}

    def recommend(s: AgentState) -> dict:
        from sqlalchemy import select
        from app.db.models import JobMatch
        ms = list(db.scalars(select(JobMatch).where(JobMatch.user_id == s["user_id"],
                                                    JobMatch.job_id.in_(s.get("kept_ids") or [0]))))
        good = sum(m.recommendation in ("Excellent", "Strong", "Good") for m in ms)
        db.add(Notification(user_id=s["user_id"], type="discovery", message=
                            f"Discovery finished: {len(ms)} jobs analysed, {good} recommended."))
        db.commit()
        return {"status": "completed", "stats": {**s["stats"], "recommended": good}}

    steps = [("load_profile", load_profile), ("discover", discover), ("persist", persist),
             ("filter", filter_), ("analyze", analyze), ("match", match), ("recommend", recommend)]
    g = StateGraph(AgentState)
    for name, fn in steps:
        g.add_node(name, node(name, fn))
    g.add_edge(START, steps[0][0])
    for (a, _), (b_, _) in zip(steps, steps[1:]):
        g.add_conditional_edges(a, lambda s, nxt=b_: END if s.get("status") in FAILED else nxt)
    g.add_edge(steps[-1][0], END)
    return g.compile()


def run_discovery(db: Session, provider: LLMProvider, sources: list[JobSource], settings: Settings,
                  user_id: int, run_id: int, query: str | None, location: str | None, limit: int,
                  sleep: Callable[[float], None] = time.sleep) -> AgentState:
    graph = build_graph(db, provider, sources, settings, sleep)
    state: AgentState = {"user_id": user_id, "run_id": run_id, "query": query, "location": location,
                         "limit": limit, "steps": 0, "errors": [], "warnings": [], "status": "running",
                         "deadline": time.monotonic() + settings.agent_timeout_seconds, "stats": {}}
    return graph.invoke(state, {"recursion_limit": settings.max_agent_steps + 5})
