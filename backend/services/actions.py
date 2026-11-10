from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from backend.auth import utcnow
from backend.database import Investigation, Proposal
from backend.services.tools import Tools


def proposal_dict(p):
    return {key: getattr(p, key) for key in ("id", "investigation_id", "title", "target", "status", "created_by", "created_at", "expires_at", "approved_by")}


def propose_action(tools: Tools, investigation_id: str):
    tools.require("propose_action")
    investigation = tools.session.get(Investigation, (tools.customer, investigation_id))
    if not investigation:
        raise HTTPException(404, "Investigation not found in the current customer scope")
    result = investigation.result
    if not result["can_recommend"]:
        raise HTTPException(409, "Evidence is insufficient; no network-change proposal is permitted")
    tools.entity(result["target"])
    now = datetime.now(timezone.utc)
    proposal = Proposal(customer_id=tools.customer, id=f"CHG-{uuid4().hex[:6].upper()}", investigation_id=investigation_id,
        created_by=tools.identity.subject, title=f"Review transport diagnostics and recovery plan for {result['target']}",
        target=result["target"], status="pending", created_at=utcnow(),
        expires_at=(now + timedelta(minutes=30)).isoformat(timespec="seconds").replace("+00:00", "Z"), approved_by=None)
    tools.session.add(proposal)
    tools.audit("propose_action", {"proposal_id": proposal.id, "investigation_id": investigation_id, "target": proposal.target})
    return proposal_dict(proposal)


def approve_action(tools: Tools, proposal_id: str):
    tools.require("approve_action")
    proposal = tools.session.get(Proposal, (tools.customer, proposal_id))
    if not proposal:
        raise HTTPException(404, "Proposal not found in the current customer scope")
    if proposal.status != "pending":
        raise HTTPException(409, "Only a pending proposal can be approved")
    if proposal.created_by == tools.identity.subject:
        raise HTTPException(403, "A proposer cannot approve their own action")
    if proposal.expires_at < utcnow():
        raise HTTPException(409, "Proposal expired; request a new investigation and proposal")
    if tools.entity(proposal.target).status != "critical":
        raise HTTPException(409, "Target state changed; reassess the proposal")
    proposal.status = "approved_for_review"
    proposal.approved_by = tools.identity.subject
    tools.audit("approve_action", {"proposal_id": proposal.id, "target": proposal.target, "execution": "unavailable_in_demo"})
    return proposal_dict(proposal)
