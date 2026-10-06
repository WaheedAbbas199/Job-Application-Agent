"""Public job-board API adapters (documented, no auth, no scraping, no CAPTCHA bypass).

Remotive: https://remotive.com/api/remote-jobs   Arbeitnow: https://www.arbeitnow.com/api/job-board-api
Fixed hosts only (no user-controlled URLs) => no SSRF surface. application_url is stored, never fetched.
"""
from datetime import datetime, timezone

import httpx

from app.core.exceptions import JobSourceError
from app.schemas import RawJob
from app.sources.base import JobSource


def _get_json(client: httpx.Client, url: str, params: dict) -> dict:
    try:
        r = client.get(url, params=params, headers={"User-Agent": "JobApplicationAgent/1.0"})
    except httpx.TimeoutException as exc:
        raise JobSourceError("Job source timed out", transient=True) from exc
    except httpx.HTTPError as exc:
        raise JobSourceError("Job source network error", transient=True) from exc
    if r.status_code == 429 or r.status_code >= 500:
        raise JobSourceError(f"Job source unavailable ({r.status_code})", transient=True)
    if r.status_code >= 400:
        raise JobSourceError(f"Job source rejected request ({r.status_code})")
    try:
        return r.json()
    except ValueError as exc:
        raise JobSourceError("Job source returned invalid JSON") from exc


def _dt(value) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str) and value:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, OSError):
        return None
    return None


class RemotiveSource(JobSource):
    name = "remotive"
    URL = "https://remotive.com/api/remote-jobs"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=15)

    def fetch(self, query, location, limit):
        data = _get_json(self.client, self.URL, {"search": query or "", "limit": limit})
        out = []
        for j in (data.get("jobs") or [])[:limit]:
            try:
                out.append(RawJob(
                    external_id=str(j["id"]), source=self.name, title=j["title"], company=j["company_name"],
                    description=j.get("description") or "", location=j.get("candidate_required_location"),
                    remote_type="remote", employment_type=(j.get("job_type") or "").replace("_", " ") or None,
                    salary_text=j.get("salary") or None, posted_at=_dt(j.get("publication_date")),
                    application_url=j.get("url"), tags=j.get("tags") or [],
                    metadata={"category": j.get("category")}))
            except (KeyError, ValueError):
                continue  # skip malformed record, keep the rest
        return out


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    URL = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=15)

    def fetch(self, query, location, limit):
        data = _get_json(self.client, self.URL, {})
        out, q = [], (query or "").lower()
        loc = (location or "").lower()
        for j in data.get("data") or []:
            hay = f"{j.get('title', '')} {j.get('description', '')} {' '.join(j.get('tags') or [])}".lower()
            if q and not any(w in hay for w in q.split()):
                continue
            if loc and loc not in (j.get("location") or "").lower() and not j.get("remote"):
                continue
            try:
                out.append(RawJob(
                    external_id=str(j["slug"]), source=self.name, title=j["title"], company=j["company_name"],
                    description=j.get("description") or "", location=j.get("location"),
                    remote_type="remote" if j.get("remote") else None,
                    employment_type=", ".join(j.get("job_types") or []) or None,
                    posted_at=_dt(j.get("created_at")), application_url=j.get("url"),
                    tags=j.get("tags") or []))
            except (KeyError, ValueError):
                continue
            if len(out) >= limit:
                break
        return out


def default_sources() -> list[JobSource]:
    return [RemotiveSource(), ArbeitnowSource()]
