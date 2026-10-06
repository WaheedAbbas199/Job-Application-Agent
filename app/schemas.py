"""Pydantic schemas: API I/O and LLM structured-output contracts."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: int
    email: str
    role: str


class DeleteAccountIn(BaseModel):
    password: str


# ---- profile
class ExperienceIn(BaseModel):
    title: str = Field(max_length=300)
    company: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None


class EducationIn(BaseModel):
    degree: str = Field(max_length=300)
    institution: str | None = None
    year: str | None = None


class ProjectIn(BaseModel):
    name: str = Field(max_length=300)
    description: str | None = None
    technologies: list[str] = []


class PreferencesIn(BaseModel):
    roles: list[str] = []
    locations: list[str] = []
    remote_type: Literal["remote", "hybrid", "onsite", "any"] = "any"
    min_salary: float | None = None
    industries: list[str] = []
    employment_types: list[str] = []


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=5000)
    years_experience: float | None = Field(default=None, ge=0, le=60)
    preferences: PreferencesIn = PreferencesIn()
    certifications: list[str] = []
    languages: list[str] = []
    skills: list[str] = Field(default=[], max_length=200)
    experiences: list[ExperienceIn] = Field(default=[], max_length=50)
    education: list[EducationIn] = Field(default=[], max_length=20)
    projects: list[ProjectIn] = Field(default=[], max_length=50)

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, v: list[str]) -> list[str]:
        seen, out = set(), []
        for s in v:
            s = s.strip()[:100]
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
        return out


# ---- LLM contracts
class ParsedCV(BaseModel):
    name: str | None = None
    email: str | None = None
    headline: str | None = None
    summary: str | None = None
    years_experience: float | None = None
    skills: list[str] = []
    experience: list[ExperienceIn] = []
    education: list[EducationIn] = []
    projects: list[ProjectIn] = []
    certifications: list[str] = []
    achievements: list[str] = []
    languages: list[str] = []
    tools: list[str] = []
    job_preferences: str | None = None


class JDAnalysis(BaseModel):
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    min_years_experience: float | None = None
    education_level: str | None = None  # none|bachelor|master|phd
    responsibilities: list[str] = []
    requirements: list[str] = []
    seniority: str | None = None
    keywords: list[str] = []
    injection_suspected: bool = False


class RawJob(BaseModel):
    external_id: str
    source: str
    title: str
    company: str
    description: str = ""
    location: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None
    salary_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    posted_at: datetime | None = None
    application_url: str | None = None
    tags: list[str] = []
    metadata: dict = {}


# ---- misc requests
class DiscoverIn(BaseModel):
    query: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=30, ge=1, le=100)


class StatusIn(BaseModel):
    status: str
    expected_version: int | None = None
    note: str | None = Field(default=None, max_length=1000)


class ApplicationPatch(BaseModel):
    notes: str | None = Field(default=None, max_length=5000)
    follow_up_date: datetime | None = None


class ApplyIn(BaseModel):
    confirm: bool = False


class DocEditIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class ApproveIn(BaseModel):
    acknowledge_unsupported: bool = False


class RegenerateIn(BaseModel):
    type: Literal["resume", "cover_letter", "recruiter_message"]


class CreateApplicationIn(BaseModel):
    job_id: int
