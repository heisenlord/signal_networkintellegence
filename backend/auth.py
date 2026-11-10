"""Local demo identities and verified production OIDC access tokens."""
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from backend.config import get_settings

CUSTOMERS = [
    ("atlas", "Atlas Mobile", "Mumbai"),
    ("horizon", "Horizon Telecom", "Bengaluru"),
    ("meridian", "Meridian Wireless", "Delhi"),
    ("nova", "Nova Networks", "Hyderabad"),
    ("summit", "Summit Communications", "Chennai"),
]
ROLES = {
    "alarm": "Alarm management",
    "performance": "Performance analysis",
    "change": "Change planning",
    "approver": "Human approver",
}
PERMISSIONS = {
    "alarm": {"read", "investigate", "draft_incident_update", "propose_action"},
    "performance": {"read", "investigate", "analyze_performance", "propose_action"},
    "change": {"read", "investigate", "prepare_change_plan", "propose_action"},
    "approver": {"read", "approve_action"},
}


@dataclass(frozen=True)
class Principal:
    customer_id: str
    role: str
    subject: str

    def require(self, permission: str):
        if permission not in PERMISSIONS.get(self.role, set()):
            raise HTTPException(403, f"Role '{self.role}' cannot {permission}")


IDENTITIES = {
    f"demo-{customer}-{role}": Principal(customer, role, f"demo:{customer}:{role}")
    for customer, _, _ in CUSTOMERS for role in ROLES
}
bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=4)
def jwks_client(url: str):
    return jwt.PyJWKClient(url, timeout=5, lifespan=300)


def authenticate(token: str) -> Principal:
    settings = get_settings()
    if settings.signal_environment == "development":
        identity = IDENTITIES.get(token)
        if identity:
            return identity
    elif token and len(token) <= 8192:
        try:
            # The allowlist is fixed by the server, never by the JWT header.
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise jwt.InvalidAlgorithmError()
            key = jwks_client(settings.signal_oidc_jwks_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"],
                issuer=settings.signal_oidc_issuer, audience=settings.signal_oidc_audience,
                options={"require": ["exp", "iat", "sub", "iss", "aud", "customer_id", "role"]})
            customer, role, subject = claims["customer_id"], claims["role"], claims["sub"]
            if (not isinstance(customer, str) or customer not in {c[0] for c in CUSTOMERS}
                    or not isinstance(role, str) or role not in ROLES
                    or not isinstance(subject, str) or not subject or len(subject) > 255):
                raise jwt.InvalidTokenError()
            return Principal(customer, role, subject)
        except jwt.PyJWTError:
            pass
    raise HTTPException(401, "A valid access token is required", headers={"WWW-Authenticate": "Bearer"})


def principal(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
    identity = authenticate(credentials.credentials if credentials else "")
    request.state.identity = identity
    return identity


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
