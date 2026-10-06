"""Analytics + career strategy computed strictly from stored data (no invented statistics)."""
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Application, ApplicationEvent, Job, JobMatch

MIN_SAMPLE = 5
_REACHED_APPLIED = {"Applied", "Assessment", "Interview", "Rejected", "Offer"}


def _rate(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def _history(db: Session, apps: list[Application]) -> dict[int, set[str]]:
    ids = [a.id for a in apps]
    h: dict[int, set[str]] = {a.id: {a.status} for a in apps}
    if ids:
        for e in db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id.in_(ids))):
            h[e.application_id].add(e.new_status)
    return h


def overview(db: Session, user_id: int) -> dict:
    apps = list(db.scalars(select(Application).where(Application.user_id == user_id)))
    hist = _history(db, apps)
    matches = list(db.scalars(select(JobMatch).where(JobMatch.user_id == user_id)))
    applied = [a for a in apps if hist[a.id] & _REACHED_APPLIED]
    interviews = [a for a in apps if "Interview" in hist[a.id]]
    offers = [a for a in apps if "Offer" in hist[a.id]]
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_([a.job_id for a in apps] or [0])))}
    miss = Counter(s for m in matches for s in (m.missing_skills or []))
    by_loc, by_role = Counter(), Counter()
    for a in interviews:
        j = jobs.get(a.job_id)
        if j:
            by_loc[j.location or "unknown"] += 1
            by_role[j.title] += 1
    return {
        "jobs_matched": len(matches), "recommended_jobs": sum(m.recommendation in ("Excellent", "Strong", "Good") for m in matches),
        "applications": len(apps), "applied": len(applied), "interviews": len(interviews), "offers": len(offers),
        "rejections": sum("Rejected" in hist[a.id] for a in apps),
        "by_status": dict(Counter(a.status for a in apps)),
        "interview_rate": _rate(len(interviews), len(applied)), "offer_rate": _rate(len(offers), len(applied)),
        "average_match_score": round(sum(m.overall_score for m in matches) / len(matches), 1) if matches else None,
        "common_missing_skills": miss.most_common(8),
        "best_performing_roles": by_role.most_common(5), "best_performing_locations": by_loc.most_common(5),
    }


def strategy(db: Session, user_id: int) -> dict:
    apps = list(db.scalars(select(Application).where(Application.user_id == user_id)))
    hist = _history(db, apps)
    applied = [a for a in apps if hist[a.id] & _REACHED_APPLIED]
    matches = {m.job_id: m for m in db.scalars(select(JobMatch).where(JobMatch.user_id == user_id))}
    recs, basis = [], {"applied": len(applied)}
    miss = Counter(s for m in matches.values() for s in (m.missing_skills or []))
    if len(matches) >= MIN_SAMPLE and miss:
        s, n = miss.most_common(1)[0]
        recs.append(f"'{s}' is missing in {n} of {len(matches)} analysed jobs - consider learning it (only add it to your CV once you actually have it).")
    if len(applied) >= MIN_SAMPLE:
        hi = [a for a in applied if matches.get(a.job_id) and matches[a.job_id].overall_score >= 80]
        lo = [a for a in applied if matches.get(a.job_id) and matches[a.job_id].overall_score < 80]
        if len(hi) >= 3 and len(lo) >= 3:
            ri = _rate(sum("Interview" in hist[a.id] for a in hi), len(hi))
            rl = _rate(sum("Interview" in hist[a.id] for a in lo), len(lo))
            basis.update(high_match_n=len(hi), low_match_n=len(lo))
            recs.append(f"Interview rate for 80+ match applications: {ri}% (n={len(hi)}) vs {rl}% (n={len(lo)}) for lower matches.")
    if not recs:
        return {"recommendations": [], "basis": basis,
                "message": f"Not enough data yet (need at least {MIN_SAMPLE} analysed jobs / applications). "
                           "Recommendations are only generated from your real history."}
    return {"recommendations": recs, "basis": basis}
