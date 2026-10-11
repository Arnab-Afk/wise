"""Teams: groups of workspace members that own projects (and so get their incident emails)."""

from fastapi import APIRouter, HTTPException, Request

from . import db, emails
from .workspaces import display, member_role, need

router = APIRouter(prefix="/v1")


def team(team_id: int) -> dict:
    row = db.one("SELECT * FROM teams WHERE id = %s", team_id)
    if not row:
        raise HTTPException(404, "Team not found.")
    return row


def _full(workspace_id: int, team_id: int | None = None) -> list[dict]:
    teams = db.query("SELECT id, name, description, created_at FROM teams WHERE workspace_id = %s"
                     " AND (%s::bigint IS NULL OR id = %s) ORDER BY name", workspace_id, team_id, team_id)
    for t in teams:
        t["members"] = db.query("SELECT u.id, u.email, u.name, u.avatar_url FROM team_members tm"
                                " JOIN users u ON u.id = tm.user_id WHERE tm.team_id = %s ORDER BY u.name, u.email", t["id"])
        t["projects"] = db.query("SELECT p.id, p.name, p.slug FROM team_projects tp JOIN projects p ON p.id = tp.project_id"
                                 " WHERE tp.team_id = %s ORDER BY p.name", t["id"])
    return teams


@router.get("/workspaces/{workspace_id}/teams")
def list_teams(workspace_id: int, request: Request):
    need(request, workspace_id, "viewer")
    return _full(workspace_id)


@router.post("/workspaces/{workspace_id}/teams")
def create_team(workspace_id: int, body: dict, request: Request):
    ctx = need(request, workspace_id, "admin")
    name = (body.get("name") or "").strip()[:50]
    if len(name) < 2:
        raise HTTPException(400, "Give the team a name.")
    if db.one("SELECT 1 FROM teams WHERE workspace_id = %s AND lower(name) = lower(%s)", workspace_id, name):
        raise HTTPException(409, "There's already a team with that name.")
    row = db.one("INSERT INTO teams (workspace_id, name, description, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
                 workspace_id, name, (body.get("description") or "").strip()[:200] or None, ctx["user"]["id"])
    for uid in body.get("member_ids") or []:
        add_member(row["id"], {"user_id": uid}, request)
    for pid in body.get("project_ids") or []:
        _own(row["id"], workspace_id, pid)
    return _full(workspace_id, row["id"])[0]


@router.patch("/teams/{team_id}")
def update_team(team_id: int, body: dict, request: Request):
    t = team(team_id)
    need(request, t["workspace_id"], "admin")
    db.query("UPDATE teams SET name = coalesce(%s, name), description = %s WHERE id = %s",
             (body.get("name") or "").strip()[:50] or None,
             (body.get("description", t["description"]) or "").strip()[:200] or None, team_id)
    if "project_ids" in body:
        db.query("DELETE FROM team_projects WHERE team_id = %s", team_id)
        for pid in body["project_ids"] or []:
            _own(team_id, t["workspace_id"], pid)
    return _full(t["workspace_id"], team_id)[0]


@router.delete("/teams/{team_id}")
def delete_team(team_id: int, request: Request):
    t = team(team_id)
    need(request, t["workspace_id"], "admin")
    db.query("DELETE FROM teams WHERE id = %s", team_id)
    return {"deleted": True}


def _own(team_id: int, workspace_id: int, project_id: int) -> None:
    if not db.one("SELECT 1 FROM projects WHERE id = %s AND workspace_id = %s", project_id, workspace_id):
        raise HTTPException(400, "That project isn't in this workspace.")
    db.query("INSERT INTO team_projects (team_id, project_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", team_id, project_id)


@router.post("/teams/{team_id}/members")
def add_member(team_id: int, body: dict, request: Request):
    t = team(team_id)
    ctx = need(request, t["workspace_id"], "admin")
    uid = int(body.get("user_id") or 0)
    if not member_role(t["workspace_id"], uid):
        raise HTTPException(400, "Only workspace members can join a team.")
    added = db.one("INSERT INTO team_members (team_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING user_id",
                   team_id, uid)
    if added and uid != ctx["user"]["id"]:
        user = db.one("SELECT email FROM users WHERE id = %s", uid)
        ws = db.one("SELECT name FROM workspaces WHERE id = %s", t["workspace_id"])
        projects = [p["name"] for p in db.query("SELECT p.name FROM team_projects tp JOIN projects p ON p.id = tp.project_id"
                                                 " WHERE tp.team_id = %s", team_id)]
        emails.added_to_team(user["email"], ws["name"], t["name"], projects, display(ctx["user"]))
    return {"added": True}


@router.delete("/teams/{team_id}/members/{user_id}")
def remove_member(team_id: int, user_id: int, request: Request):
    t = team(team_id)
    need(request, t["workspace_id"], "admin")
    db.query("DELETE FROM team_members WHERE team_id = %s AND user_id = %s", team_id, user_id)
    return {"removed": True}


def on_call(project_id: int) -> list[dict]:
    """Who gets a project's incident emails: its owning teams' members, or everyone if no team owns it."""
    owners = db.query("SELECT DISTINCT u.* FROM team_projects tp JOIN team_members tm ON tm.team_id = tp.team_id"
                      " JOIN users u ON u.id = tm.user_id WHERE tp.project_id = %s", project_id)
    if owners:
        return owners
    return db.query("SELECT u.* FROM workspace_members m JOIN users u ON u.id = m.user_id"
                    " WHERE m.workspace_id = (SELECT workspace_id FROM projects WHERE id = %s)", project_id)
