"""Coding-agent accounts the team connects: Claude (Anthropic API key) or Cursor (Cursor API key).

Claude is connected with an API key from the Claude Console, not a claude.ai login: Anthropic
doesn't allow third-party products to offer claude.ai login or subscription limits.
"""

from fastapi import APIRouter, HTTPException, Request

from . import db, emails, secrets

PROVIDERS = {
    "claude": {"name": "Claude Agent", "credential": "Anthropic API key (Claude Console)",
               "prefix": "sk-ant-", "default_model": "claude-opus-5-5"},
    "cursor": {"name": "Cursor Agent", "credential": "Cursor API key", "prefix": "",
               "default_model": None},
}
PUBLIC = ("id, provider, label, credential_hint, model, is_default, status, status_detail,"
          " created_at, last_used_at")

router = APIRouter(prefix="/v1")


@router.get("/providers")
def providers():
    return [{"id": k, **{f: v[f] for f in ("name", "credential", "default_model")}}
            for k, v in PROVIDERS.items()]


@router.get("/connections")
def list_connections():
    return db.query(f"SELECT {PUBLIC} FROM connections ORDER BY is_default DESC, id")


def _tell_admins(request: Request, provider: str, label: str, connected: bool) -> None:
    from .workspaces import admins, display
    ctx = getattr(request.state, "auth", None)
    if not ctx or not ctx.get("workspace"):
        return
    for a in admins(ctx["workspace"]["id"]):
        emails.coding_agent_changed(a["email"], ctx["workspace"]["name"], provider, label, connected, display(ctx["user"]))


@router.post("/connections")
def create_connection(body: dict, request: Request):
    provider, key = body.get("provider"), (body.get("api_key") or "").strip()
    if provider not in PROVIDERS:
        raise HTTPException(400, f"provider must be one of {sorted(PROVIDERS)}")
    if len(key) < 12 or not key.startswith(PROVIDERS[provider]["prefix"]):
        raise HTTPException(400, f"That doesn't look like a {PROVIDERS[provider]['credential']}.")
    first = not db.one("SELECT 1 FROM connections LIMIT 1")
    row = db.one(
        f"INSERT INTO connections (provider, label, credential, credential_hint, model, is_default,"
        f" status) VALUES (%s, %s, %s, %s, %s, %s, 'testing') RETURNING {PUBLIC}",
        provider, body.get("label") or PROVIDERS[provider]["name"], secrets.encrypt(key),
        key[-4:], body.get("model") or PROVIDERS[provider]["default_model"],
        bool(body.get("is_default")) or first)
    if row["is_default"]:
        db.query("UPDATE connections SET is_default = false WHERE id <> %s", row["id"])
    _tell_admins(request, provider, row["label"], True)
    return row


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: int):
    """The runner checks the key with the provider and updates the status."""
    row = db.one(f"UPDATE connections SET status = 'testing', status_detail = NULL WHERE id = %s"
                 f" RETURNING {PUBLIC}", connection_id)
    if not row:
        raise HTTPException(404, "connection not found")
    return row


@router.post("/connections/{connection_id}/default")
def make_default(connection_id: int):
    if not db.one("SELECT 1 FROM connections WHERE id = %s", connection_id):
        raise HTTPException(404, "connection not found")
    db.query("UPDATE connections SET is_default = (id = %s)", connection_id)
    return list_connections()


@router.delete("/connections/{connection_id}")
def delete_connection(connection_id: int, request: Request):
    row = db.one("DELETE FROM connections WHERE id = %s RETURNING provider, label", connection_id)
    if row:
        _tell_admins(request, row["provider"], row["label"], False)
    return {"deleted": True}


@router.get("/fix-jobs")
def list_fix_jobs(incident_id: int | None = None):
    return db.query(
        "SELECT id, incident_id, provider, service, branch, status, commit_sha, checkpoint_id,"
        " tests_passed, cost_usd, created_at, finished_at FROM fix_jobs"
        " WHERE %s::bigint IS NULL OR incident_id = %s ORDER BY id DESC LIMIT 100",
        incident_id, incident_id)


@router.get("/fix-jobs/{job_id}")
def get_fix_job(job_id: int):
    row = db.one("SELECT * FROM fix_jobs WHERE id = %s", job_id)
    if not row:
        raise HTTPException(404, "fix job not found")
    return row
