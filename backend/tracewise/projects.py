"""Project settings: ingest keys (which decide where telemetry lands), renaming and deletion.

The repository path and deployer URL are set by whoever operates this install, not through the
API: letting tenants point them at arbitrary server paths or internal URLs would be unsafe.
"""

from fastapi import APIRouter, HTTPException, Request

from . import db, tenancy
from .workspaces import need

router = APIRouter(prefix="/v1/projects")


def project(project_id: int) -> dict:
    row = db.one("SELECT * FROM projects WHERE id = %s", project_id)
    if not row:
        raise HTTPException(404, "Project not found.")
    return row


@router.get("/{project_id}")
def get_project(project_id: int, request: Request):
    p = project(project_id)
    need(request, p["workspace_id"], "viewer")
    stats = db.one("SELECT (SELECT count(*) FROM services WHERE project_id = %s) AS services,"
                   " (SELECT count(*) FROM incidents WHERE project_id = %s) AS incidents,"
                   " (SELECT count(*) FROM sources WHERE project_id = %s) AS sources", project_id, project_id, project_id)
    return {**{k: p[k] for k in ("id", "workspace_id", "name", "slug", "description", "created_at")},
            "can_deploy": bool(p["deployer_url"]), "has_repo": bool(p["repo_path"]), "action_policy": p["action_policy"], **stats}


@router.patch("/{project_id}")
def update_project(project_id: int, body: dict, request: Request):
    p = project(project_id)
    need(request, p["workspace_id"], "admin")
    name = (body.get("name") or p["name"]).strip()[:60]
    if len(name) < 2:
        raise HTTPException(400, "Name must be at least 2 characters.")
    return db.one("UPDATE projects SET name = %s, description = %s WHERE id = %s RETURNING id, name, slug, description",
                  name, (body.get("description", p["description"]) or "").strip()[:300] or None, project_id)


@router.delete("/{project_id}")
def delete_project(project_id: int, body: dict, request: Request):
    """Deletes the project and everything in it. The caller must type the project's name."""
    p = project(project_id)
    need(request, p["workspace_id"], "owner")
    if (body.get("confirm") or "").strip() != p["name"]:
        raise HTTPException(400, f"Type the project name ({p['name']}) to confirm.")
    db.query("DELETE FROM projects WHERE id = %s", project_id)
    tenancy.forget_keys()
    return {"deleted": True}


@router.get("/{project_id}/keys")
def list_keys(project_id: int, request: Request):
    need(request, project(project_id)["workspace_id"], "admin")
    return db.query("SELECT k.id, k.name, k.prefix, k.created_at, k.last_used_at, u.email AS created_by"
                    " FROM project_keys k LEFT JOIN users u ON u.id = k.created_by"
                    " WHERE k.project_id = %s AND k.revoked_at IS NULL ORDER BY k.created_at", project_id)


@router.post("/{project_id}/keys")
def create_key(project_id: int, body: dict, request: Request):
    """Returns the key once. Only a hash is kept."""
    ctx = need(request, project(project_id)["workspace_id"], "admin")
    name = (body.get("name") or "Ingest key").strip()[:60]
    key = tenancy.new_key()
    row = db.one("INSERT INTO project_keys (project_id, name, prefix, key_hash, created_by)"
                 " VALUES (%s, %s, %s, %s, %s) RETURNING id, name, prefix, created_at",
                 project_id, name, key[:10], tenancy.digest(key), ctx["user"]["id"])
    return {**row, "key": key}


@router.delete("/{project_id}/keys/{key_id}")
def revoke_key(project_id: int, key_id: int, request: Request):
    need(request, project(project_id)["workspace_id"], "admin")
    db.query("UPDATE project_keys SET revoked_at = now() WHERE id = %s AND project_id = %s", key_id, project_id)
    tenancy.forget_keys()
    return {"revoked": True}
