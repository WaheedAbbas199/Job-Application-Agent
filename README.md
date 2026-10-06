# Job Application Agent

Agentic job-search assistant: discovers real postings, analyses job descriptions, matches them to your CV with a
**deterministic hybrid score**, shows skill gaps, prepares **truthful** tailored documents, and tracks applications.
**Nothing is ever submitted without your explicit approval.**

Classification: **Production Candidate** (see "Honest status" for what is and isn't verified).

## Architecture

```
Browser (HTML/CSS/JS SPA) -> FastAPI (/api/v1: JWT, RBAC, rate limit) -> Services -> PostgreSQL (SQLite for dev/tests)
                                   |  BackgroundTasks (app/services/pipelines.py)   +-- LLMProvider (Gemini | Local fallback)
                                   v                                                +-- JobSource adapters (Remotive, Arbeitnow)
   LangGraph: load_profile -> discover -> persist(normalize+dedup) -> filter -> analyze -> match -> recommend
   (max steps, wall-clock timeout, bounded transient retries, per-node error records, no cycles)
   Human review/approval is in the API: prepare -> review/edit -> approve -> confirm "apply"
```

Rules implemented: LLM output is never trusted (parse -> Pydantic -> grounding against source text -> repair/retry ->
safe fallback). CV/job text is untrusted DATA (instruction-like lines stripped and flagged). Generated text mentioning a
skill not in your profile is rejected/flagged and **blocks approval**. Documents are versioned, never overwritten.

## Quick start (local, no Docker, no API key)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                    # Windows: copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload                           # http://localhost:8000  (API docs: /api/docs)
pytest -q
```
Without `GEMINI_API_KEY` the app still works (deterministic parsers, grounded templates, local hashing embeddings).
Set the key to enable Gemini for structured extraction, cover letters and explanations.

## Docker
```bash
cp .env.example .env   # set JWT_SECRET (>=32 chars), POSTGRES_PASSWORD, GEMINI_API_KEY (optional)
docker compose up --build
```
In `ENVIRONMENT=production` the app refuses to start with a weak/default `JWT_SECRET`.

## Configuration
See `.env.example`. Matching weights (`W_SKILL`, `W_EXPERIENCE`, ... must sum to 1) and thresholds (`T_EXCELLENT`, ...) are configurable.

## Usage flow
1. Register -> upload CV -> **Apply to profile** -> set preferences.
2. Jobs -> **Discover & match** (background run) -> open a job for the score breakdown.
3. Save -> **Prepare documents** -> edit / approve / reject.
4. **Mark as applied** (needs an approved document + confirmation). You submit on the employer site yourself.
5. Track status, follow-up reminders, interview prep, analytics.

## Honest status

| Area | Status |
|---|---|
| API, services, LangGraph workflow, auth, RBAC, audit, rate limiting | Implemented; **52 automated tests pass** (SQLite) |
| Alembic migration | Upgrade/downgrade/`alembic check` verified on **SQLite only** |
| Live boot (uvicorn + migrated DB, health/ready, static, headers) | Smoke-tested |
| Gemini provider, job-source adapters | Tested against **mocked HTTP only** (no real key/network in build env) |
| Frontend | Syntax-checked and served; **not tested in a real browser** |
| PostgreSQL, Redis, Dockerfile, compose, GitHub Actions | Written, **never executed** |

## Known gaps (not production-ready until addressed)
- **pgvector**: embeddings stored as JSON, compared in Python (OK for hundreds of jobs/user, not 100k+).
- **Celery worker**: work runs via FastAPI `BackgroundTasks`; functions take primitive args so they can move to Celery. No reaper for runs stuck in `running`.
- **Automated submission**: intentionally not implemented; user submits manually.
- **Live company research** for interview prep: not configured.
- **Virus scanning**: only extension/magic-byte/size checks.
- Companies are not normalised into their own table.
- Redis rate-limit/readiness paths untested; in-memory limiter is per-process.
- Token in `sessionStorage` (XSS-sensitive; CSP set). Heuristic CV parsing is conservative; messy layouts need manual edits.
- Frontend functional but not polished; no browser E2E tests.

## Layout
`app/core` config/logging/security/retry/rate-limit · `app/db` models+session · `app/services` domain logic ·
`app/agents/graph.py` LangGraph · `app/sources` job adapters · `app/llm` provider+safety · `app/api/v1` routers ·
`app/static` frontend · `alembic/` migrations · `tests/`.
