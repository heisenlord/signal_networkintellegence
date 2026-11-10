"""Public demo identities; bind localhost. Replace with verified OIDC claims in production."""
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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


def principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
    identity = IDENTITIES.get(credentials.credentials) if credentials else None
    if identity is None:
        raise HTTPException(401, "Select a demo identity or supply a valid bearer token")
    return identity


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
