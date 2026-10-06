"""Central configuration. Every tunable value comes from environment variables."""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Job Application Agent"
    environment: str = "development"
    database_url: str = "sqlite:///./jobagent.db"
    redis_url: str | None = None

    gemini_api_key: str | None = None
    llm_model: str = "gemini-2.0-flash"
    embedding_model: str = "text-embedding-004"
    llm_timeout_seconds: float = 30.0

    jwt_secret: str = INSECURE_DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    cors_origins: str = "http://localhost:8000"
    admin_emails: str = ""

    max_retries: int = 3
    max_agent_steps: int = 20
    agent_timeout_seconds: float = 120.0
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10
    file_size_limit_mb: int = 5
    upload_dir: str = "./uploads"
    followup_days: int = 7
    job_fetch_limit: int = 50

    # Matching weights (must sum to 1.0) and recommendation thresholds
    w_skill: float = 0.35
    w_experience: float = 0.20
    w_role: float = 0.15
    w_education: float = 0.10
    w_location: float = 0.10
    w_salary: float = 0.05
    w_preference: float = 0.05
    t_excellent: float = 90
    t_strong: float = 80
    t_good: float = 70
    t_weak: float = 60

    @model_validator(mode="after")
    def _check(self):
        total = (self.w_skill + self.w_experience + self.w_role + self.w_education
                 + self.w_location + self.w_salary + self.w_preference)
        if abs(total - 1.0) > 1e-6:
            raise ValueError("matching weights must sum to 1.0")
        if self.environment == "production" and (
            self.jwt_secret == INSECURE_DEFAULT_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError("JWT_SECRET must be set to a strong value (>=32 chars) in production")
        return self

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_list(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
