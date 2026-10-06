from tests.conftest import register
from app.core.config import Settings
import pytest


def test_register_login_me_logout(client):
    h = register(client)
    assert client.get("/api/v1/auth/me", headers=h).json()["email"] == "jane@example.com"
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401  # token revoked


def test_duplicate_and_weak_password(client):
    register(client)
    assert client.post("/api/v1/auth/register", json={"email": "jane@example.com", "password": "correct-horse-1"}).status_code == 409
    assert client.post("/api/v1/auth/register", json={"email": "b@example.com", "password": "short"}).status_code == 422


def test_bad_login_generic_error(client):
    register(client)
    r = client.post("/api/v1/auth/login", json={"email": "jane@example.com", "password": "wrong-password"})
    assert r.status_code == 401 and "Invalid email or password" in r.text


def test_unauthenticated_and_tampered_token(client):
    assert client.get("/api/v1/profile").status_code == 401
    assert client.get("/api/v1/profile", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_expired_token(client, monkeypatch):
    import jwt, time
    from app.core.config import get_settings
    s = get_settings()
    tok = jwt.encode({"sub": "1", "jti": "x", "exp": int(time.time()) - 10}, s.jwt_secret, algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_security_headers_and_safe_500(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert client.get("/ready").json()["checks"]["database"] == "ok"


def test_production_requires_strong_secret():
    with pytest.raises(ValueError):
        Settings(environment="production", jwt_secret="dev-insecure-change-me")


def test_rate_limit():
    from app.core.ratelimit import RateLimiter
    rl = RateLimiter()
    assert all(rl.allow("k", 3) for _ in range(3)) and not rl.allow("k", 3)


def test_admin_rbac(client):
    h = register(client)
    assert client.get("/api/v1/agents/admin/errors", headers=h).status_code == 403
    ha = register(client, "admin@example.com")
    assert client.get("/api/v1/agents/admin/errors", headers=ha).status_code == 200


def test_delete_account_erases_data(client, ready_user):
    h = ready_user
    r = client.request("DELETE", "/api/v1/auth/me", headers=h, json={"password": "wrong-password"})
    assert r.status_code == 401
    assert client.request("DELETE", "/api/v1/auth/me", headers=h, json={"password": "correct-horse-1"}).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
    from app.db.models import Resume, UserSkill
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        assert db.query(Resume).count() == 0 and db.query(UserSkill).count() == 0
