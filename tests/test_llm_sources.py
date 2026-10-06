"""Gemini provider + job-source adapters against mocked HTTP (no network, no real API key used)."""
import json

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import JobSourceError, LLMError
from app.llm.provider import GeminiProvider
from app.llm.structured import structured_call
from app.schemas import JDAnalysis
from app.sources.api_sources import ArbeitnowSource, RemotiveSource


def gem(handler):
    return GeminiProvider(Settings(gemini_api_key="test-key", max_retries=2),
                          httpx.Client(transport=httpx.MockTransport(handler)))


def ok(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_gemini_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        assert req.headers["x-goog-api-key"] == "test-key" and "key=" not in str(req.url)  # key never in URL
        return httpx.Response(429) if calls["n"] < 3 else ok("hello")
    assert gem(handler).generate_text("s", "p") == "hello" and calls["n"] == 3


def test_gemini_does_not_retry_permanent_errors(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401)
    with pytest.raises(LLMError):
        gem(handler).generate_text("s", "p")
    assert calls["n"] == 1


def test_gemini_retries_are_bounded(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(503)
    with pytest.raises(LLMError):
        gem(handler).generate_text("s", "p")
    assert calls["n"] == 3  # 1 try + max_retries(2)


def test_structured_output_repair_loop():
    outs = iter(["not json", '{"required_skills": "oops"}', json.dumps({"required_skills": ["Python"]})])
    p = gem(lambda r: ok(next(outs)))
    assert structured_call(p, "s", "p", JDAnalysis, 3).required_skills == ["Python"]


def test_structured_output_fails_safely():
    p = gem(lambda r: ok("garbage"))
    with pytest.raises(LLMError):
        structured_call(p, "s", "p", JDAnalysis, 2)


def test_llm_parse_is_grounded_in_cv_text():
    from app.services.cv_parser import parse_cv
    cv = "Jane Doe\njane@example.com\nSkills\nPython, SQL\nExperience\nDev at X 2020 - 2022"
    lie = json.dumps({"name": "Jane Doe", "email": "fake@evil.com", "skills": ["Python", "AWS", "Kubernetes"]})
    parsed, parser, _ = parse_cv(cv, gem(lambda r: ok(lie)), 1)
    assert parser == "llm" and parsed.skills == ["Python"] and parsed.email is None


def test_llm_failure_falls_back_to_heuristics():
    from app.services.cv_parser import parse_cv
    parsed, parser, _ = parse_cv("Jane Doe\nSkills\nPython and Docker experience here", gem(lambda r: httpx.Response(401)), 1)
    assert parser == "heuristic" and "Python" in parsed.skills


def test_gemini_embeddings():
    p = gem(lambda r: httpx.Response(200, json={"embeddings": [{"values": [0.1, 0.2]}]}))
    assert p.embed(["x"]) == [[0.1, 0.2]]


def test_remotive_adapter_and_malformed_records():
    data = {"jobs": [{"id": 1, "title": "ML Engineer", "company_name": "A", "description": "<p>x</p>",
                      "candidate_required_location": "Worldwide", "url": "https://r/1", "salary": "$100k - $120k",
                      "publication_date": "2026-01-02T10:00:00", "tags": ["python"], "job_type": "full_time"},
                     {"id": 2}]}  # malformed -> skipped
    src = RemotiveSource(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))))
    jobs = src.fetch("ml", None, 10)
    assert len(jobs) == 1 and jobs[0].source == "remotive" and jobs[0].remote_type == "remote"


def test_arbeitnow_filtering():
    data = {"data": [{"slug": "a", "title": "Python Dev", "company_name": "X", "description": "d", "location": "Berlin",
                      "remote": False, "tags": [], "job_types": ["full time"], "url": "u", "created_at": 1700000000},
                     {"slug": "b", "title": "Chef", "company_name": "Y", "description": "d", "location": "Paris",
                      "remote": False, "tags": [], "job_types": [], "url": "u2", "created_at": 1700000000}]}
    src = ArbeitnowSource(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))))
    assert [j.external_id for j in src.fetch("python", None, 10)] == ["a"]


@pytest.mark.parametrize("resp,exc", [(httpx.Response(500), True), (httpx.Response(403), False), (httpx.Response(200, text="<html>"), False)])
def test_source_errors(resp, exc):
    src = RemotiveSource(httpx.Client(transport=httpx.MockTransport(lambda r: resp)))
    with pytest.raises(JobSourceError) as e:
        src.fetch("x", None, 5)
    assert e.value.transient is exc
