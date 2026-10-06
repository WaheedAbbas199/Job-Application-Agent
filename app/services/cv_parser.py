"""CV text extraction, structured extraction (LLM with grounded validation, heuristic fallback)."""
import io
import re
import zipfile

from app.core.exceptions import ResumeParsingError
from app.llm.provider import LLMProvider
from app.llm.safety import SYSTEM_GUARD, detect_injection, strip_injection_lines, wrap_untrusted
from app.llm.structured import structured_call
from app.schemas import EducationIn, ExperienceIn, ParsedCV, ProjectIn
from app.services.skills import extract_skills

ALLOWED_EXT = {"pdf": "application/pdf", "txt": "text/plain",
               "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MIN_TEXT_CHARS = 30


def validate_upload(filename: str, content: bytes, max_bytes: int) -> str:
    """Validate extension + magic bytes + size. Returns the normalised extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise ResumeParsingError("Unsupported file type. Upload PDF, DOCX or TXT.")
    if not content:
        raise ResumeParsingError("File is empty.")
    if len(content) > max_bytes:
        raise ResumeParsingError(f"File too large (limit {max_bytes // (1024 * 1024)} MB).")
    if ext == "pdf" and not content.startswith(b"%PDF"):
        raise ResumeParsingError("File content does not match PDF format.")
    if ext == "docx" and not (content.startswith(b"PK") and zipfile.is_zipfile(io.BytesIO(content))):
        raise ResumeParsingError("File content does not match DOCX format.")
    if ext == "txt" and b"\x00" in content[:1024]:
        raise ResumeParsingError("File content does not look like text.")
    return ext


def sanitize_filename(name: str) -> str:
    base = re.sub(r"[^\w.\- ]", "_", name.replace("\\", "/").split("/")[-1])
    return base[:120] or "resume"


def extract_text(content: bytes, ext: str) -> str:
    try:
        if ext == "pdf":
            from pypdf import PdfReader
            text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(content)).pages)
        elif ext == "docx":
            import docx
            d = docx.Document(io.BytesIO(content))
            text = "\n".join(p.text for p in d.paragraphs)
            for t in d.tables:
                for row in t.rows:
                    text += "\n" + " | ".join(c.text for c in row.cells)
        else:
            text = content.decode("utf-8", errors="replace")
    except Exception as exc:  # corrupted document
        raise ResumeParsingError("Could not read the document; it may be corrupted.") from exc
    text = re.sub(r"[ \t]+", " ", text.replace("\r", "")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) < MIN_TEXT_CHARS:
        raise ResumeParsingError("No readable text found in the document (empty or scanned image).")
    return text


_HEADS = {
    "summary": {"summary", "profile", "objective", "about me", "professional summary"},
    "skills": {"skills", "technical skills", "core skills", "key skills"},
    "experience": {"experience", "work experience", "professional experience", "employment", "work history"},
    "education": {"education", "academic background", "qualifications"},
    "projects": {"projects", "personal projects", "academic projects"},
    "certifications": {"certifications", "certificates", "licenses"},
    "achievements": {"achievements", "awards", "honors"},
    "languages": {"languages"},
}


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    cur = "header"
    for line in text.split("\n"):
        key = line.strip().rstrip(":").lower()
        hit = next((s for s, names in _HEADS.items() if key in names), None)
        if hit:
            cur = hit
            sections.setdefault(cur, [])
        else:
            sections[cur].append(line.strip())
    return sections


def _blocks(lines: list[str]) -> list[list[str]]:
    blocks, cur = [], []
    for ln in lines:
        if ln:
            cur.append(ln.lstrip("-•* ").strip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


_RANGE = re.compile(r"((?:19|20)\d{2})\s*(?:-|–|—|to)\s*((?:19|20)\d{2}|present|current|now)", re.I)


def heuristic_parse(text: str) -> ParsedCV:
    sec = split_sections(text)
    header = [l for l in sec["header"] if l]
    name = next((l for l in header[:3] if 1 < len(l.split()) <= 4 and not re.search(r"[@\d]", l)), None)
    email = (re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text) or [None])[0]
    exp_lines = sec.get("experience", [])
    experience = []
    for b in _blocks(exp_lines):
        rng = _RANGE.search(" ".join(b))
        experience.append(ExperienceIn(title=b[0][:300], start=rng.group(1) if rng else None,
                                       end=rng.group(2) if rng else None,
                                       description=" ".join(b[1:]) or None))
    years, now_year = 0.0, 2026
    for m in _RANGE.finditer("\n".join(exp_lines)):
        end = now_year if m.group(2).lower() in ("present", "current", "now") else int(m.group(2))
        years += max(0, end - int(m.group(1)))
    education = [EducationIn(degree=b[0][:300], institution=b[1] if len(b) > 1 else None)
                 for b in _blocks(sec.get("education", []))]
    projects = []
    for b in _blocks(sec.get("projects", [])):
        body = " ".join(b)
        projects.append(ProjectIn(name=b[0][:300], description=" ".join(b[1:]) or None,
                                  technologies=extract_skills(body)))
    langs = [x.strip() for l in sec.get("languages", []) for x in re.split(r"[,;|]", l) if x.strip()]
    return ParsedCV(
        name=name, email=email, headline=header[1] if len(header) > 1 and "@" not in header[1] else None,
        summary=" ".join(l for l in sec.get("summary", []) if l) or None,
        years_experience=years or None, skills=extract_skills(text), experience=experience,
        education=education, projects=projects,
        certifications=[l.lstrip("-•* ") for l in sec.get("certifications", []) if l],
        achievements=[l.lstrip("-•* ") for l in sec.get("achievements", []) if l], languages=langs)


def ground(parsed: ParsedCV, raw_text: str) -> ParsedCV:
    """Business-rule validation: nothing may appear in structured data that is not in the CV text."""
    low = raw_text.lower()
    parsed.skills = [s for s in dict.fromkeys(parsed.skills) if s.lower() in low]
    parsed.tools = [s for s in parsed.tools if s.lower() in low]
    if parsed.email and parsed.email.lower() not in low:
        parsed.email = None
    if parsed.name and parsed.name.lower() not in low:
        parsed.name = None
    for p in parsed.projects:
        p.technologies = [t for t in p.technologies if t.lower() in low]
    return parsed


_SYSTEM = (SYSTEM_GUARD + " Extract structured data from the CV. Use null / empty lists for anything "
           "not explicitly stated. Never infer or invent skills, employers, degrees or dates.")


def parse_cv(text: str, provider: LLMProvider, max_retries: int) -> tuple[ParsedCV, str, bool]:
    """Returns (parsed, parser_name, injection_suspected)."""
    inj = detect_injection(text)
    if inj:
        text = strip_injection_lines(text)  # instruction-like lines are discarded, never interpreted
    if provider.available:
        try:
            schema = ParsedCV.model_json_schema()
            prompt = f"Return JSON matching this schema: {schema}\n\nCV:\n{wrap_untrusted(text)}"
            return ground(structured_call(provider, _SYSTEM, prompt, ParsedCV, max_retries), text), "llm", inj
        except Exception:
            pass  # fall back to deterministic parser
    return ground(heuristic_parse(text), text), "heuristic", inj
