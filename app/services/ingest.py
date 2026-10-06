"""Job normalisation + idempotent deduplication."""
import hashlib
import html
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Job
from app.schemas import RawJob


def clean_html(raw: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw or "", flags=re.S | re.I)
    s = re.sub(r"</?(br|p|li|ul|ol|div|h[1-6])[^>]*>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def make_dedup_key(company: str, title: str, location: str | None) -> str:
    return hashlib.sha1(f"{_norm(company)}|{_norm(title)}|{_norm(location)}".encode()).hexdigest()


def similarity(a: str, b: str) -> float:
    ta, tb = set(_norm(a).split()), set(_norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


_SAL = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k)?", re.I)


def parse_salary(text: str | None) -> tuple[float | None, float | None, str | None]:
    if not text:
        return None, None, None
    nums = []
    for m in _SAL.finditer(text):
        v = float(m.group(1).replace(",", ""))
        nums.append(v * 1000 if m.group(2) else v)
    nums = [n for n in nums if n >= 100]
    cur = "USD" if "$" in text or "usd" in text.lower() else ("EUR" if "€" in text else None)
    if not nums:
        return None, None, cur
    return min(nums), max(nums), cur


def detect_remote(raw: RawJob, desc: str) -> str:
    if raw.remote_type in ("remote", "hybrid", "onsite"):
        return raw.remote_type
    probe = f"{raw.title} {raw.location or ''} {desc[:600]}".lower()
    if "hybrid" in probe:
        return "hybrid"
    if "remote" in probe:
        return "remote"
    return "onsite" if raw.location else "unknown"


def normalize(raw: RawJob) -> dict:
    desc = clean_html(raw.description)
    smin, smax, cur = raw.salary_min, raw.salary_max, None
    if smin is None and smax is None:
        smin, smax, cur = parse_salary(raw.salary_text)
    return dict(
        external_id=raw.external_id, source=raw.source, title=raw.title.strip()[:500],
        company=raw.company.strip()[:300], description=desc,
        location=(raw.location or "").strip()[:300] or None, remote_type=detect_remote(raw, desc),
        employment_type=raw.employment_type, salary_min=smin, salary_max=smax, salary_currency=cur,
        posted_at=raw.posted_at, application_url=(raw.application_url or None),
        dedup_key=make_dedup_key(raw.company, raw.title, raw.location),
        meta={"tags": raw.tags, **raw.metadata})


def find_duplicate(db: Session, d: dict) -> Job | None:
    j = db.scalar(select(Job).where(Job.source == d["source"], Job.external_id == d["external_id"]))
    if j:
        return j
    if d["application_url"]:
        j = db.scalar(select(Job).where(Job.application_url == d["application_url"]))
        if j:
            return j
    for cand in db.scalars(select(Job).where(Job.dedup_key == d["dedup_key"]).limit(20)):
        if not d["description"] or not cand.description or similarity(d["description"], cand.description) >= 0.85:
            return cand
    return None


def upsert_job(db: Session, raw: RawJob) -> tuple[Job, bool]:
    d = normalize(raw)
    dup = find_duplicate(db, d)
    if dup:
        return dup, False
    job = Job(**d)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:  # concurrent insert of the same (source, external_id)
        db.rollback()
        return db.scalar(select(Job).where(Job.source == d["source"], Job.external_id == d["external_id"])), False
    return job, True
