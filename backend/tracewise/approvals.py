"""Human approval for production actions.

When a project's action policy is "approve", every action the agent wants to take (roll back,
restart, flip a flag, deploy a fix) becomes an approval request. The on-call people are asked in
Slack, Discord, email and the web console; the agent waits for the answer. Rejected or unanswered
requests come back to the agent as a refusal, so it escalates instead.
"""

import time

from fastapi import APIRouter, HTTPException, Request

from . import db, emails

router = APIRouter(prefix="/v1")
TIMEOUT_MINUTES = 10
LABEL = {"rollback": "Roll back", "restart": "Restart", "set_flag": "Change feature flag", "deploy_fix": "Deploy code fix"}


def describe(a: dict) -> str:
    p = a.get("params") or {}
    if a["kind"] == "set_flag":
        return f"Set flag {a['target']} to {p.get('value')}"
    if a["kind"] == "rollback":
        return f"Roll back {a['target']}" + (f" to {p['to_sha']}" if p.get("to_sha") else " to its previous version")
    if a["kind"] == "deploy_fix":
        return f"Deploy fix #{p.get('job_id')} to {a['target']}" + (f" (commit {p['commit']})" if p.get("commit") else "")
    return f"{LABEL.get(a['kind'], a['kind'])} {a['target']}"


def policy(project_id: int) -> str:
    row = db.one("SELECT action_policy FROM projects WHERE id = %s", project_id)
    return row["action_policy"] if row else "approve"


def request(incident: dict, key: str, kind: str, target: str, params: dict) -> dict:
    """Create (or, for a resumed run, find) the approval request for an action."""
    existing = db.one("SELECT * FROM approvals WHERE action_key = %s", key)
    if existing:
        return existing
    a = db.one("INSERT INTO approvals (incident_id, project_id, action_key, kind, target, params, expires_at)"
               " VALUES (%s, %s, %s, %s, %s, %s, now() + make_interval(mins => %s)) RETURNING *",
               incident["id"], incident["project_id"], key, kind, target, db.jsonb(params), TIMEOUT_MINUTES)
    db.add_step(incident["id"], "approval", f"Waiting for approval: {describe(a)}",
                {"approval_id": a["id"], "kind": kind, "target": target, "params": params}, phase="act")
    from .teams import on_call
    for person in on_call(incident["project_id"]):
        emails.approval_requested(person["email"], incident, describe(a), params.get("reason") or "", TIMEOUT_MINUTES)
    return a


def wait(approval_id: int, heartbeat) -> dict:
    """Block until someone decides or the request expires."""
    while True:
        a = db.one("SELECT * FROM approvals WHERE id = %s", approval_id)
        if a["status"] != "pending":
            return a
        if db.one("SELECT now() > %s AS late", a["expires_at"])["late"]:
            return decide(approval_id, "expired", None, "system", f"Nobody answered within {TIMEOUT_MINUTES} minutes")
        heartbeat()
        time.sleep(3)


def decide(approval_id: int, decision: str, who: str | None, via: str, note: str | None = None) -> dict:
    a = db.one("UPDATE approvals SET status = %s, decided_by = %s, decided_via = %s, note = %s, decided_at = now()"
               " WHERE id = %s AND status = 'pending' RETURNING *", decision, who, via, note, approval_id)
    if not a:
        a = db.one("SELECT * FROM approvals WHERE id = %s", approval_id)
        if a and a["status"] != "pending":
            return a
        raise HTTPException(404, "Approval not found.")
    verb = {"approved": "Approved", "rejected": "Rejected", "expired": "Expired"}[decision]
    title = f"{verb}: {describe(a)}" + (f" by {who}" if who else "") + (f" via {via}" if via not in ("system",) else "")
    db.add_step(a["incident_id"], "approval_decision", title,
                {"approval_id": a["id"], "decision": decision, "by": who, "via": via, "note": note}, phase="act")
    return a


def member_by_email(workspace_id: int, email: str | None) -> dict | None:
    """A workspace member allowed to act on incidents (member or above), by email."""
    if not email:
        return None
    return db.one("SELECT u.*, m.role FROM workspace_members m JOIN users u ON u.id = m.user_id"
                  " WHERE m.workspace_id = %s AND lower(u.email) = lower(%s) AND m.role IN ('owner', 'admin', 'member')",
                  workspace_id, email)


# ---------------------------------------------------------------- API (web console)

def pid(request: Request) -> int:
    return request.state.auth["project"]["id"]


@router.get("/approvals")
def list_approvals(request: Request, incident_id: int | None = None, pending: bool = False):
    return db.query("SELECT * FROM approvals WHERE project_id = %s AND (%s::bigint IS NULL OR incident_id = %s)"
                    " AND (NOT %s OR status = 'pending') ORDER BY id DESC LIMIT 100",
                    pid(request), incident_id, incident_id, pending)


@router.post("/approvals/{approval_id}/decide")
def decide_web(approval_id: int, body: dict, request: Request):
    from .auth import rank
    ctx = request.state.auth
    if not ctx.get("user") or rank(ctx["role"]) < rank("member"):
        raise HTTPException(403, "Only members and above can approve production actions.")
    a = db.one("SELECT * FROM approvals WHERE id = %s AND project_id = %s", approval_id, pid(request))
    if not a:
        raise HTTPException(404, "Approval not found.")
    decision = body.get("decision")
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be approved or rejected")
    who = ctx["user"].get("name") or ctx["user"]["email"]
    return decide(approval_id, decision, who, "web", (body.get("note") or "").strip()[:500] or None)


@router.patch("/projects/{project_id}/policy")
def set_policy(project_id: int, body: dict, request: Request):
    from .workspaces import need
    p = db.one("SELECT workspace_id FROM projects WHERE id = %s", project_id)
    if not p:
        raise HTTPException(404, "Project not found.")
    need(request, p["workspace_id"], "admin")
    value = body.get("action_policy")
    if value not in ("auto", "approve"):
        raise HTTPException(400, "action_policy must be auto or approve")
    return db.one("UPDATE projects SET action_policy = %s WHERE id = %s RETURNING id, action_policy", value, project_id)
