"""Workspaces, members and roles, invitations, projects, and the email log."""

import re
import secrets as pysecrets

from fastapi import APIRouter, HTTPException, Request

from . import db, emails
from .auth import ROLES, digest, normalise_email, rank, require

router = APIRouter(prefix="/v1")
INVITE_DAYS = 7


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"


def display(user: dict) -> str:
    return user.get("name") or user["email"]


def member_role(workspace_id: int, user_id: int) -> str | None:
    row = db.one("SELECT role FROM workspace_members WHERE workspace_id = %s AND user_id = %s", workspace_id, user_id)
    return row["role"] if row else None


def need(request: Request, workspace_id: int, role: str) -> dict:
    ctx = require(request)
    have = member_role(workspace_id, ctx["user"]["id"])
    if rank(have) < rank(role):
        raise HTTPException(403 if have else 404, f"You need to be {role} or above in this workspace." if have
                            else "Workspace not found.")
    return {**ctx, "role": have}


def admins(workspace_id: int, exclude: int | None = None) -> list[dict]:
    return db.query("SELECT u.* FROM workspace_members m JOIN users u ON u.id = m.user_id"
                    " WHERE m.workspace_id = %s AND m.role IN ('owner', 'admin') AND u.id <> coalesce(%s, 0)",
                    workspace_id, exclude)


# ---------------------------------------------------------------- workspaces

@router.get("/workspaces")
def list_workspaces(request: Request):
    ctx = require(request)
    return db.query(
        "SELECT w.*, m.role, (SELECT count(*) FROM workspace_members x WHERE x.workspace_id = w.id) AS members"
        " FROM workspace_members m JOIN workspaces w ON w.id = m.workspace_id WHERE m.user_id = %s"
        " ORDER BY m.created_at", ctx["user"]["id"])


@router.post("/workspaces")
def create_workspace(body: dict, request: Request):
    ctx = require(request)
    name = (body.get("name") or "").strip()[:60]
    if len(name) < 2:
        raise HTTPException(400, "Give the workspace a name (at least 2 characters).")
    slug = slugify(name)
    while db.one("SELECT 1 FROM workspaces WHERE slug = %s", slug):
        slug = f"{slugify(name)[:33]}-{pysecrets.token_hex(3)}"
    ws = db.one("INSERT INTO workspaces (name, slug, created_by) VALUES (%s, %s, %s) RETURNING *",
                name, slug, ctx["user"]["id"])
    db.query("INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s, %s, 'owner')", ws["id"], ctx["user"]["id"])
    emails.workspace_created(ctx["user"]["email"], name)
    return {**ws, "role": "owner"}


@router.patch("/workspaces/{workspace_id}")
def rename_workspace(workspace_id: int, body: dict, request: Request):
    need(request, workspace_id, "admin")
    name = (body.get("name") or "").strip()[:60]
    if len(name) < 2:
        raise HTTPException(400, "Name must be at least 2 characters.")
    return db.one("UPDATE workspaces SET name = %s WHERE id = %s RETURNING *", name, workspace_id)


@router.get("/workspaces/{workspace_id}/members")
def members(workspace_id: int, request: Request):
    ctx = need(request, workspace_id, "viewer")
    people = db.query(
        "SELECT u.id, u.email, u.name, u.avatar_url, u.last_login_at, m.role, m.created_at AS joined_at"
        " FROM workspace_members m JOIN users u ON u.id = m.user_id WHERE m.workspace_id = %s"
        " ORDER BY array_position(ARRAY['owner','admin','member','viewer'], m.role), m.created_at", workspace_id)
    invites = []
    if rank(ctx["role"]) >= rank("admin"):
        invites = db.query(
            "SELECT i.id, i.email, i.role, i.created_at, i.expires_at, u.name AS invited_by_name, u.email AS invited_by_email"
            " FROM invites i LEFT JOIN users u ON u.id = i.invited_by WHERE i.workspace_id = %s"
            " AND i.accepted_at IS NULL AND i.revoked_at IS NULL ORDER BY i.created_at DESC", workspace_id)
    return {"members": people, "invites": invites, "role": ctx["role"]}


# ---------------------------------------------------------------- invitations

def _invite_url(token: str) -> str:
    return f"{emails.WEB_URL}/invite/{token}"


def _send_invite(workspace: dict, inviter: dict, email: str, role: str) -> dict:
    db.query("UPDATE invites SET revoked_at = now() WHERE workspace_id = %s AND email = %s"
             " AND accepted_at IS NULL AND revoked_at IS NULL", workspace["id"], email)
    token = pysecrets.token_urlsafe(24)
    row = db.one("INSERT INTO invites (workspace_id, email, role, token_hash, invited_by, expires_at)"
                 " VALUES (%s, %s, %s, %s, %s, now() + make_interval(days => %s))"
                 " RETURNING id, email, role, created_at, expires_at",
                 workspace["id"], email, role, digest(token), inviter["id"], INVITE_DAYS)
    emails.invite(email, display(inviter), workspace["name"], role, _invite_url(token), INVITE_DAYS)
    return row


@router.post("/workspaces/{workspace_id}/invites")
def invite(workspace_id: int, body: dict, request: Request):
    ctx = need(request, workspace_id, "admin")
    role = body.get("role", "member")
    if role not in ("admin", "member", "viewer"):
        raise HTTPException(400, "role must be admin, member or viewer")
    raw = body.get("emails") or [body.get("email", "")]
    addresses = sorted({normalise_email(e) for e in (raw if isinstance(raw, list) else re.split(r"[,\s;]+", raw)) if e})
    if not addresses or len(addresses) > 20:
        raise HTTPException(400, "Invite between 1 and 20 people at a time.")
    ws = db.one("SELECT * FROM workspaces WHERE id = %s", workspace_id)
    sent, skipped = [], []
    for email in addresses:
        if db.one("SELECT 1 FROM workspace_members m JOIN users u ON u.id = m.user_id"
                  " WHERE m.workspace_id = %s AND u.email = %s", workspace_id, email):
            skipped.append({"email": email, "reason": "already a member"})
            continue
        sent.append(_send_invite(ws, ctx["user"], email, role))
    return {"sent": sent, "skipped": skipped}


@router.post("/invites/{invite_id}/resend")
def resend(invite_id: int, request: Request):
    inv = db.one("SELECT * FROM invites WHERE id = %s AND accepted_at IS NULL AND revoked_at IS NULL", invite_id)
    if not inv:
        raise HTTPException(404, "Invitation not found.")
    ctx = need(request, inv["workspace_id"], "admin")
    ws = db.one("SELECT * FROM workspaces WHERE id = %s", inv["workspace_id"])
    return _send_invite(ws, ctx["user"], inv["email"], inv["role"])


@router.delete("/invites/{invite_id}")
def revoke(invite_id: int, request: Request):
    inv = db.one("SELECT * FROM invites WHERE id = %s", invite_id)
    if not inv:
        raise HTTPException(404, "Invitation not found.")
    need(request, inv["workspace_id"], "admin")
    db.query("UPDATE invites SET revoked_at = now() WHERE id = %s", invite_id)
    return {"revoked": True}


def _find_invite(token: str) -> dict | None:
    return db.one(
        "SELECT i.*, w.name AS workspace_name, u.name AS inviter_name, u.email AS inviter_email"
        " FROM invites i JOIN workspaces w ON w.id = i.workspace_id LEFT JOIN users u ON u.id = i.invited_by"
        " WHERE i.token_hash = %s", digest(token))


@router.get("/invites/preview")
def preview(token: str):
    """Public: what an invitation link is for, so the page can show it before sign-in."""
    inv = _find_invite(token)
    if not inv:
        raise HTTPException(404, "This invitation link isn't valid.")
    state = ("accepted" if inv["accepted_at"] else "revoked" if inv["revoked_at"] else
             "expired" if inv["expires_at"] < db.one("SELECT now() AS t")["t"] else "pending")
    return {"workspace": inv["workspace_name"], "role": inv["role"], "email": inv["email"], "state": state,
            "invited_by": inv["inviter_name"] or inv["inviter_email"]}


@router.post("/invites/accept")
def accept(body: dict, request: Request):
    ctx = require(request)
    inv = _find_invite(body.get("token", ""))
    if not inv or inv["revoked_at"]:
        raise HTTPException(404, "This invitation isn't valid any more.")
    if inv["accepted_at"]:
        raise HTTPException(409, "This invitation was already used.")
    if inv["expires_at"] < db.one("SELECT now() AS t")["t"]:
        raise HTTPException(410, "This invitation has expired. Ask for a new one.")
    if inv["email"] != ctx["user"]["email"]:
        raise HTTPException(403, f"This invitation is for {inv['email']}. Sign in with that email to accept it.")
    db.query("INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s, %s, %s)"
             " ON CONFLICT (workspace_id, user_id) DO NOTHING", inv["workspace_id"], ctx["user"]["id"], inv["role"])
    db.query("UPDATE invites SET accepted_at = now() WHERE id = %s", inv["id"])
    emails.joined_workspace(ctx["user"]["email"], inv["workspace_name"], inv["role"])
    if inv["inviter_email"]:
        emails.invite_accepted(inv["inviter_email"], display(ctx["user"]), inv["workspace_name"], inv["role"])
    return {"workspace_id": inv["workspace_id"], "workspace": inv["workspace_name"], "role": inv["role"]}


# ---------------------------------------------------------------- members

@router.patch("/workspaces/{workspace_id}/members/{user_id}")
def change_role(workspace_id: int, user_id: int, body: dict, request: Request):
    ctx = need(request, workspace_id, "admin")
    role = body.get("role")
    current = member_role(workspace_id, user_id)
    if role not in ROLES or not current:
        raise HTTPException(400, "Unknown member or role.")
    if "owner" in (role, current) and ctx["role"] != "owner":
        raise HTTPException(403, "Only an owner can change ownership.")
    if current == "owner" and role != "owner" and db.one(
            "SELECT count(*) AS n FROM workspace_members WHERE workspace_id = %s AND role = 'owner'", workspace_id)["n"] < 2:
        raise HTTPException(400, "A workspace needs at least one owner. Make someone else owner first.")
    db.query("UPDATE workspace_members SET role = %s WHERE workspace_id = %s AND user_id = %s", role, workspace_id, user_id)
    target = db.one("SELECT * FROM users WHERE id = %s", user_id)
    ws = db.one("SELECT name FROM workspaces WHERE id = %s", workspace_id)
    if user_id != ctx["user"]["id"]:
        emails.role_changed(target["email"], ws["name"], role, display(ctx["user"]))
    return {"user_id": user_id, "role": role}


@router.delete("/workspaces/{workspace_id}/members/{user_id}")
def remove_member(workspace_id: int, user_id: int, request: Request):
    ctx = require(request)
    leaving = user_id == ctx["user"]["id"]
    if not leaving:
        ctx = need(request, workspace_id, "admin")
    current = member_role(workspace_id, user_id)
    if not current:
        raise HTTPException(404, "Not a member.")
    if current == "owner" and db.one(
            "SELECT count(*) AS n FROM workspace_members WHERE workspace_id = %s AND role = 'owner'", workspace_id)["n"] < 2:
        raise HTTPException(400, "The last owner can't leave. Make someone else owner first.")
    if current == "owner" and not leaving and ctx["role"] != "owner":
        raise HTTPException(403, "Only an owner can remove an owner.")
    db.query("DELETE FROM workspace_members WHERE workspace_id = %s AND user_id = %s", workspace_id, user_id)
    if not leaving:
        target = db.one("SELECT email FROM users WHERE id = %s", user_id)
        ws = db.one("SELECT name FROM workspaces WHERE id = %s", workspace_id)
        emails.removed_from_workspace(target["email"], ws["name"], display(ctx["user"]))
    return {"removed": True}


# ---------------------------------------------------------------- projects

@router.get("/workspaces/{workspace_id}/projects")
def projects(workspace_id: int, request: Request):
    need(request, workspace_id, "viewer")
    return db.query("SELECT p.*, u.name AS created_by_name FROM projects p LEFT JOIN users u ON u.id = p.created_by"
                    " WHERE p.workspace_id = %s ORDER BY p.created_at", workspace_id)


@router.post("/workspaces/{workspace_id}/projects")
def create_project(workspace_id: int, body: dict, request: Request):
    ctx = need(request, workspace_id, "admin")
    name = (body.get("name") or "").strip()[:60]
    if len(name) < 2:
        raise HTTPException(400, "Give the project a name (at least 2 characters).")
    slug = slugify(name)
    if db.one("SELECT 1 FROM projects WHERE workspace_id = %s AND slug = %s", workspace_id, slug):
        raise HTTPException(409, "A project with that name already exists.")
    row = db.one("INSERT INTO projects (workspace_id, name, slug, description, created_by)"
                 " VALUES (%s, %s, %s, %s, %s) RETURNING *", workspace_id, name, slug,
                 (body.get("description") or "").strip()[:300] or None, ctx["user"]["id"])
    ws = db.one("SELECT name FROM workspaces WHERE id = %s", workspace_id)
    for a in admins(workspace_id, exclude=ctx["user"]["id"]):
        emails.project_created(a["email"], ws["name"], name, display(ctx["user"]))
    return row


# ---------------------------------------------------------------- email log

@router.get("/workspaces/{workspace_id}/emails")
def email_log(workspace_id: int, request: Request, limit: int = 100):
    """Emails sent to this workspace's members and invitees (admins only), newest first."""
    need(request, workspace_id, "admin")
    return db.query(
        "SELECT id, to_email, template, subject, status, error, created_at, sent_at FROM email_log"
        " WHERE to_email IN (SELECT u.email FROM workspace_members m JOIN users u ON u.id = m.user_id"
        "                    WHERE m.workspace_id = %s UNION SELECT email FROM invites WHERE workspace_id = %s)"
        " ORDER BY id DESC LIMIT %s", workspace_id, workspace_id, min(limit, 500))


@router.get("/workspaces/{workspace_id}/emails/{email_id}")
def email_detail(workspace_id: int, email_id: int, request: Request):
    need(request, workspace_id, "admin")
    row = db.one(
        "SELECT * FROM email_log WHERE id = %s AND to_email IN (SELECT u.email FROM workspace_members m"
        " JOIN users u ON u.id = m.user_id WHERE m.workspace_id = %s UNION SELECT email FROM invites"
        " WHERE workspace_id = %s)", email_id, workspace_id, workspace_id)
    if not row:
        raise HTTPException(404, "Email not found.")
    return row


# ---------------------------------------------------------------- notifications from the rest of the app

def notify_admins(workspace_id: int | None, send) -> None:
    """Run send(user) for every owner/admin of the workspace."""
    if workspace_id:
        for a in admins(workspace_id):
            send(a)
