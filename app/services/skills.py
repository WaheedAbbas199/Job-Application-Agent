"""Skill vocabulary + extraction. Extraction only reports skills literally present in the text."""
import re

SKILLS: dict[str, list[str]] = {
    "Python": ["python"], "SQL": ["sql"], "Java": ["java"], "JavaScript": ["javascript", "js"],
    "TypeScript": ["typescript"], "C++": ["c++"], "C#": ["c#"], "Go": ["golang"], "Rust": ["rust"],
    "R": [], "Scala": ["scala"], "Kotlin": ["kotlin"], "Swift": ["swift"], "PHP": ["php"], "Ruby": ["ruby"],
    "Bash": ["bash", "shell scripting"], "HTML": ["html", "html5"], "CSS": ["css", "css3"],
    "React": ["react", "react.js", "reactjs"], "Angular": ["angular"], "Vue": ["vue", "vue.js"],
    "Node.js": ["node.js", "nodejs", "node"], "Django": ["django"], "Flask": ["flask"],
    "FastAPI": ["fastapi"], "Spring Boot": ["spring boot", "spring"], ".NET": [".net", "dotnet"],
    "REST APIs": ["rest api", "rest apis", "restful", "rest"], "GraphQL": ["graphql"],
    "PostgreSQL": ["postgresql", "postgres"], "MySQL": ["mysql"], "MongoDB": ["mongodb"],
    "Redis": ["redis"], "SQLAlchemy": ["sqlalchemy"], "Elasticsearch": ["elasticsearch"],
    "Pandas": ["pandas"], "NumPy": ["numpy"], "Scikit-learn": ["scikit-learn", "sklearn"],
    "TensorFlow": ["tensorflow"], "Keras": ["keras"], "PyTorch": ["pytorch"], "XGBoost": ["xgboost"],
    "Machine Learning": ["machine learning", "ml"], "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"], "Computer Vision": ["computer vision"],
    "LLMs": ["llm", "llms", "large language models"], "RAG": ["rag", "retrieval augmented generation",
                                                               "retrieval-augmented generation"],
    "LangChain": ["langchain"], "LangGraph": ["langgraph"], "Hugging Face": ["hugging face", "huggingface"],
    "Ollama": ["ollama"], "Prompt Engineering": ["prompt engineering"], "Vector Databases": [
        "vector database", "vector databases", "pgvector", "chromadb", "pinecone", "faiss"],
    "Data Analysis": ["data analysis", "data analytics"], "Statistics": ["statistics"],
    "Power BI": ["power bi", "powerbi"], "Tableau": ["tableau"], "Excel": ["excel"],
    "Streamlit": ["streamlit"], "Spark": ["spark", "pyspark"], "Airflow": ["airflow"], "Kafka": ["kafka"],
    "Docker": ["docker"], "Kubernetes": ["kubernetes", "k8s"], "AWS": ["aws", "amazon web services"],
    "Azure": ["azure"], "GCP": ["gcp", "google cloud"], "Terraform": ["terraform"],
    "CI/CD": ["ci/cd", "cicd", "github actions", "jenkins"], "Git": ["git", "github", "gitlab"],
    "Linux": ["linux"], "Microservices": ["microservices"], "System Design": ["system design"],
    "Pytest": ["pytest"], "Testing": ["unit testing", "test automation"], "Agile": ["agile", "scrum"],
    "Celery": ["celery"], "OpenAI API": ["openai"], "MLOps": ["mlops"], "Data Engineering": [
        "data engineering", "etl"], "Selenium": ["selenium"], "Figma": ["figma"],
}

_PATTERNS: list[tuple[str, re.Pattern]] = []
for _name, _aliases in SKILLS.items():
    for _a in {_name.lower(), *_aliases}:
        _PATTERNS.append((_name, re.compile(r"(?<![\w+#.])" + re.escape(_a) + r"(?![\w+#]|\.\w)", re.I)))

# 'R', 'Go' and 'Swift' collide with ordinary words: require explicit case-sensitive forms.
_CASE_SENSITIVE = {"R": None, "Go": None}


def extract_skills(text: str) -> list[str]:
    found: dict[str, int] = {}
    for name, pat in _PATTERNS:
        if name in _CASE_SENSITIVE:
            continue
        m = pat.search(text or "")
        if m and name not in found:
            found[name] = m.start()
    if re.search(r"(?<![\w+#.])R(?![\w+#.])(?=[,;\s]*(?:and\s)?(?:Python|SQL|Pandas|ggplot|Shiny|statistics))|\bR programming\b", text or ""):
        found.setdefault("R", 0)
    if re.search(r"\bGolang\b|\bGo\s+(?:programming|language)\b", text or ""):
        found.setdefault("Go", 0)
    return [n for n, _ in sorted(found.items(), key=lambda kv: kv[1])]


def canonical(name: str) -> str:
    low = name.strip().lower()
    for canon, aliases in SKILLS.items():
        if low == canon.lower() or low in aliases:
            return canon
    return name.strip()


def unsupported_skills(text: str, allowed: set[str]) -> list[str]:
    """Skills mentioned in generated text that are not in the user's profile (truthfulness guard)."""
    allowed_l = {canonical(a).lower() for a in allowed}
    return [s for s in extract_skills(text) if s.lower() not in allowed_l]
