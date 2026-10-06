"""Interview prep built from the job post and the candidate's REAL profile only."""
from app.db.models import Job, JobMatch
from app.services.profile import ProfileBundle

BEHAVIORAL = [
    "Tell me about a time you had to learn a new technology quickly.",
    "Describe a disagreement with a teammate and how you resolved it.",
    "Tell me about a project you are proud of and your specific contribution.",
    "Describe a time you debugged a difficult problem.",
]


def build_interview_prep(job: Job, b: ProfileBundle, match: JobMatch | None) -> dict:
    analysis = job.analysis or {}
    req = analysis.get("required_skills") or []
    have = {s.lower() for s in (match.matched_skills if match else [])} or {s.lower() for s in b.skills}
    technical = []
    for s in req[:8]:
        owned = s.lower() in have
        technical.append({"question": f"Explain how you have used {s} and the trade-offs you considered."
                          if owned else f"This role uses {s}. How would you approach getting productive with it?",
                          "candidate_has_skill": owned})
    project_q = [{"question": f"Walk me through '{p.name}': problem, design decisions, results.",
                  "answer_outline": [x for x in [p.description, ("Technologies: " + ", ".join(p.technologies))
                                                 if p.technologies else None] if x]} for p in b.projects[:4]]
    role_q = [f"Why are you interested in the {job.title} role at {job.company}?",
              "What would you do in your first 30 days?"]
    answers = []
    for e in b.experiences[:3]:
        answers.append({"for": e.title, "talking_points": [x for x in [e.company, e.description] if x]})
    return {
        "company_research": {"note": "Live company research is not configured (no web-research integration). "
                                     "Use the job description facts below.", "company": job.company,
                             "from_job_post": {"location": job.location, "remote_type": job.remote_type,
                                               "responsibilities": (job.responsibilities or [])[:8]}},
        "role_questions": role_q, "technical_questions": technical, "behavioral_questions": BEHAVIORAL,
        "project_questions": project_q, "suggested_answer_material": answers,
        "mock_interview": role_q + [t["question"] for t in technical[:4]] + BEHAVIORAL[:2]
                          + [q["question"] for q in project_q[:2]],
        "skill_gaps_to_prepare": (match.missing_skills if match else []),
        "note": "Answers must use only your real experience; nothing here is invented.",
    }
