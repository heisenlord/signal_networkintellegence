"""Production trust boundaries: real signatures, rejection paths and HTTP limits."""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.auth import authenticate
from backend.config import Settings
from backend.main import investigation_slots
from backend.mcp_server import invoke
from backend.security import SecurityMiddleware


def production_settings(**changes):
    return Settings(signal_environment="production", signal_allowed_hosts=["signal.example.com", "localhost"],
        signal_oidc_issuer="https://identity.example.com/", signal_oidc_audience="signal-api",
        signal_oidc_jwks_url="https://identity.example.com/jwks", **changes)


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def access_token(key, **changes):
    now = datetime.now(timezone.utc)
    claims = {"iss": "https://identity.example.com/", "aud": "signal-api", "sub": "operator-123",
        "customer_id": "horizon", "role": "alarm", "iat": now, "exp": now + timedelta(minutes=5), **changes}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture
def oidc(monkeypatch, signing_key):
    settings = production_settings()
    monkeypatch.setattr("backend.auth.get_settings", lambda: settings)
    monkeypatch.setattr("backend.auth.jwks_client", lambda url: SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=signing_key.public_key())))
    return settings


def test_signed_identity_scopes_api_to_verified_customer(client, signing_key, oidc):
    token = access_token(signing_key)
    result = client.get("/api/v1/overview?customer_id=atlas", headers={"Authorization": f"Bearer {token}"})
    assert result.status_code == 200
    assert result.json()["customer_id"] == "horizon"
    identity = client.get("/api/v1/session", headers={"Authorization": f"Bearer {token}"}).json()
    assert identity == {"customer_id": "horizon", "role": "alarm", "subject": "operator-123"}
    assert token not in str(identity)


@pytest.mark.parametrize("changes", [
    {"exp": datetime(2020, 1, 1, tzinfo=timezone.utc)}, {"aud": "another-api"},
    {"iss": "https://attacker.example/"}, {"role": "admin"}, {"customer_id": "unknown"},
    {"customer_id": ["horizon"]}, {"role": ["alarm"]}, {"sub": ""},
    {"exp": None}, {"exp": []}, {"iat": None},
    {"iat": datetime.now(timezone.utc) + timedelta(hours=1)},
])
def test_invalid_claims_are_rejected(signing_key, oidc, changes):
    with pytest.raises(HTTPException) as error:
        authenticate(access_token(signing_key, **changes))
    assert error.value.status_code == 401
    assert error.value.headers["WWW-Authenticate"] == "Bearer"


def test_forged_missing_claim_and_demo_tokens_are_rejected(signing_key, oidc):
    claims = jwt.decode(access_token(signing_key), signing_key.public_key(), algorithms=["RS256"], audience="signal-api")
    del claims["exp"]
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in ("demo-atlas-alarm", "broken", "", access_token(other_key),
            jwt.encode(claims, signing_key, algorithm="RS256"), jwt.encode(claims, "x" * 64, algorithm="HS256")):
        with pytest.raises(HTTPException) as error:
            authenticate(token)
        assert error.value.status_code == 401


def test_jwks_failure_does_not_expose_provider_details(monkeypatch, signing_key, oidc):
    def unavailable(token):
        raise jwt.PyJWKClientError("private endpoint credentials")
    monkeypatch.setattr("backend.auth.jwks_client", lambda url: SimpleNamespace(get_signing_key_from_jwt=unavailable))
    with pytest.raises(HTTPException) as error:
        authenticate(access_token(signing_key))
    assert "private" not in str(error.value.detail)


def test_production_configuration_fails_closed(monkeypatch):
    for name in ("SIGNAL_OIDC_ISSUER", "SIGNAL_OIDC_AUDIENCE", "SIGNAL_OIDC_JWKS_URL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        Settings(signal_environment="production")
    for changes in ({"signal_allowed_hosts": ["*"]}, {"signal_oidc_jwks_url": "http://identity.example.com/jwks"}):
        values = production_settings().model_dump()
        values.update(changes)
        with pytest.raises(ValidationError):
            Settings(**values)


def test_security_headers_auth_challenge_and_host_rejection(client):
    result = client.get("/api/v1/overview")
    assert result.status_code == 401
    assert result.headers["WWW-Authenticate"] == "Bearer"
    assert result.headers["X-Content-Type-Options"] == "nosniff"
    assert result.headers["X-Frame-Options"] == "DENY"
    assert result.headers["Cache-Control"] == "no-store"
    assert "script-src 'self'" in result.headers["Content-Security-Policy"]
    assert result.headers["X-Request-ID"] == result.json()["request_id"]
    result = client.get("/api/health", headers={"Host": "attacker.example"})
    assert result.status_code == 400
    assert result.headers["X-Frame-Options"] == "DENY"


def test_chunked_oversize_body_is_rejected_before_parsing(client, headers):
    result = client.post("/api/v1/investigations", headers=headers, content=iter([b"x" * 9000, b"x" * 9000]))
    assert result.status_code == 413


def test_rate_limit_ignores_spoofed_forwarded_headers_and_preserves_health():
    async def ok(request):
        return JSONResponse({"status": "ok"})
    app = Starlette(routes=[Route("/", ok), Route("/api/health", ok)])
    app.add_middleware(SecurityMiddleware, settings=Settings(signal_requests_per_minute=10))
    with TestClient(app) as client:
        for i in range(10):
            assert client.get("/", headers={"X-Forwarded-For": f"192.0.2.{i}"}).status_code == 200
        result = client.get("/")
        assert result.status_code == 429
        assert int(result.headers["Retry-After"]) > 0
        assert client.get("/api/health").status_code == 200


def test_investigation_admission_is_bounded(client, headers):
    held = 0
    try:
        while investigation_slots.acquire(blocking=False):
            held += 1
        response = client.post("/api/v1/investigations", headers=headers, json={"incident_id": "INC-1005"})
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "5"
    finally:
        for _ in range(held):
            investigation_slots.release()


def test_demo_mcp_is_disabled_in_production(monkeypatch):
    monkeypatch.setattr("backend.mcp_server.get_settings", production_settings)
    with pytest.raises(ValueError, match="disabled in production"):
        invoke("get_entity", "CELL-101")


def test_per_identity_investigation_rate_limit(client, monkeypatch):
    from backend import main
    monkeypatch.setattr(main, "production", True)
    monkeypatch.setattr(main.settings, "signal_investigations_per_minute", 1)
    monkeypatch.setattr(main, "investigate", lambda *args: {"result": "test"})
    main.investigation_rates.clear()
    try:
        headers = {"Authorization": "Bearer demo-nova-performance"}
        assert client.post("/api/v1/investigations", headers=headers, json={"incident_id": "INC-1005"}).status_code == 200
        response = client.post("/api/v1/investigations", headers=headers, json={"incident_id": "INC-1005"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers
    finally:
        main.investigation_rates.clear()


def test_render_hostname_and_cors_origins_are_validated(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "signal-api.onrender.com")
    monkeypatch.delenv("SIGNAL_ALLOWED_HOSTS", raising=False)
    settings = Settings(signal_environment="production", signal_oidc_issuer="https://identity.example.com/",
        signal_oidc_audience="signal-api", signal_oidc_jwks_url="https://identity.example.com/jwks",
        signal_allowed_origins=["https://signal.vercel.app"])
    assert settings.signal_allowed_hosts == ["signal-api.onrender.com", "localhost"]
    for origin in ("https://*.vercel.app", "http://signal.vercel.app", "https://signal.vercel.app/", "https://user:secret@signal.vercel.app"):
        with pytest.raises(ValidationError):
            production_settings(signal_allowed_origins=[origin])


def test_production_startup_serves_frontend_and_hides_demo_endpoints(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>Signal production build</html>")
    env = {**os.environ, "SIGNAL_ENVIRONMENT": "production", "SIGNAL_ALLOWED_HOSTS": '["testserver", "localhost"]',
        "SIGNAL_OIDC_ISSUER": "https://identity.example.com/", "SIGNAL_OIDC_AUDIENCE": "signal-api",
        "SIGNAL_OIDC_JWKS_URL": "https://identity.example.com/jwks", "SIGNAL_STATIC_DIR": str(static),
        "SIGNAL_DATABASE_URL": f"sqlite:///{tmp_path}/production.db"}
    env["SIGNAL_ALLOWED_ORIGINS"] = '["https://signal.vercel.app"]'
    script = '''
from fastapi.testclient import TestClient
from backend.main import app
with TestClient(app) as client:
    assert client.get('/api/config').json() == {'authentication': 'oidc'}
    for path in ('/docs', '/redoc', '/openapi.json', '/api/v1/demo/sessions'):
        assert client.get(path).status_code == 404, path
    response = client.get('/api/v1/overview', headers={'Authorization': 'Bearer demo-atlas-alarm'})
    assert response.status_code == 401
    assert response.headers['Strict-Transport-Security'] == 'max-age=31536000'
    assert 'Signal production build' in client.get('/').text
    assert client.get('/api/health').json()['status'] == 'ok'
    preflight_headers = {'Origin': 'https://signal.vercel.app', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'}
    response = client.options('/api/v1/investigations', headers=preflight_headers)
    assert response.status_code == 200
    assert response.headers['Access-Control-Allow-Origin'] == 'https://signal.vercel.app'
    assert 'Access-Control-Allow-Credentials' not in response.headers
    preflight_headers['Origin'] = 'https://attacker.vercel.app'
    response = client.options('/api/v1/investigations', headers=preflight_headers)
    assert response.status_code == 400
    assert 'Access-Control-Allow-Origin' not in response.headers
'''
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
