"""Sources API: list what can be connected, connect pull sources, see what's sending data."""

import json
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .. import config, db, secrets
from . import catalog
from .pull import KINDS, SourceError

router = APIRouter(prefix="/v1")
PUBLIC = ("id, kind, name, mode, config, secret_fields, enabled, status, status_detail,"
          " last_polled_at, last_received_at, items_received, created_at")
SYSLOG_PORT = int(os.environ.get("TW_SYSLOG_PORT", "5514"))
AGENT_FILE = os.environ.get("TW_AGENT_FILE", "/app/cli/tracewise")


def public_url(request: Request) -> str:
    return os.environ.get("TW_PUBLIC_URL") or str(request.base_url).rstrip("/")


@router.get("/source-types")
def source_types(request: Request):
    """Everything Tracewise can read from, with setup steps for this install."""
    from .receivers import ingest_key
    pull = [cls.describe() for kind, cls in KINDS.items() if kind != "opensearch"]
    # Only fill in the real key for callers who already have it.
    key = config.INGEST_KEY if config.INGEST_KEY and ingest_key(request) == config.INGEST_KEY else "<ingest key>"
    return {"pull": pull, "push": catalog.render(public_url(request), key, SYSLOG_PORT)}


@router.get("/sources")
def list_sources():
    rows = db.query(f"SELECT {PUBLIC} FROM sources ORDER BY mode, kind, name")
    recent = {r["source"]: r for r in db.query(
        "SELECT source, count(*) AS logs_1h, max(ts) AS last_log FROM log_events"
        " WHERE ts > now() - interval '1 hour' AND source IS NOT NULL GROUP BY source")}
    for r in rows:
        key = r["kind"] if r["mode"] == "pull" else (
            r["kind"] if r["name"] == r["kind"] else f"{r['kind']}:{r['name']}")
        r["logs_last_hour"] = (recent.get(f"{r['kind']}:{r['name']}") or recent.get(key) or {}).get("logs_1h", 0)
    return rows


def split_fields(kind: str, body: dict) -> tuple[dict, dict]:
    cls = KINDS[kind]
    secret_names = {f["name"] for f in cls.fields if f["type"] == "secret"}
    known = {f["name"] for f in cls.fields} | {"interval_seconds"}
    values = body.get("config") or {}
    unknown = set(values) - known
    if unknown:
        raise HTTPException(400, f"unknown fields for {kind}: {sorted(unknown)}")
    cfg = {k: v for k, v in values.items() if k not in secret_names}
    sec = {k: v for k, v in values.items() if k in secret_names and v}
    return cfg, sec


@router.post("/sources")
def create_source(body: dict, request: Request):
    kind = body.get("kind")
    if kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(KINDS)}")
    cfg, sec = split_fields(kind, body)
    missing = [f["label"] for f in KINDS[kind].fields
               if f["required"] and not (cfg.get(f["name"]) or sec.get(f["name"]))]
    if missing:
        raise HTTPException(400, f"missing: {', '.join(missing)}")
    name = body.get("name") or kind
    try:
        row = db.one(
            f"INSERT INTO sources (kind, name, mode, config, credential, secret_fields, status)"
            f" VALUES (%s, %s, 'pull', %s, %s, %s, 'testing') RETURNING {PUBLIC}",
            kind, name, db.jsonb(cfg), secrets.encrypt(json.dumps(sec)) if sec else None, sorted(sec))
        ctx = getattr(request.state, "auth", None)
        if ctx and ctx.get("workspace"):
            from .. import emails
            from ..workspaces import admins, display
            for a in admins(ctx["workspace"]["id"]):
                emails.source_connected(a["email"], ctx["workspace"]["name"], KINDS[kind].label, name, display(ctx["user"]))
        return row
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(409, f"a {kind} source named {name!r} already exists")
        raise


@router.patch("/sources/{source_id}")
def update_source(source_id: int, body: dict):
    row = db.one("SELECT * FROM sources WHERE id = %s", source_id)
    if not row:
        raise HTTPException(404, "source not found")
    if "enabled" in body:
        db.query("UPDATE sources SET enabled = %s WHERE id = %s", bool(body["enabled"]), source_id)
    if body.get("config") and row["mode"] == "pull":
        cfg, sec = split_fields(row["kind"], body)
        old = json.loads(secrets.decrypt(row["credential"])) if row["credential"] else {}
        merged = {**old, **sec}
        db.query("UPDATE sources SET config = config || %s, credential = %s, secret_fields = %s,"
                 " status = 'testing', state = '{}' WHERE id = %s",
                 db.jsonb(cfg), secrets.encrypt(json.dumps(merged)) if merged else None,
                 sorted(merged), source_id)
    return db.one(f"SELECT {PUBLIC} FROM sources WHERE id = %s", source_id)


@router.post("/sources/{source_id}/test")
def test_source(source_id: int):
    row = db.one(f"UPDATE sources SET status = 'testing', status_detail = NULL WHERE id = %s"
                 f" AND mode = 'pull' RETURNING {PUBLIC}", source_id)
    if not row:
        raise HTTPException(404, "pull source not found")
    return row


@router.delete("/sources/{source_id}")
def delete_source(source_id: int):
    db.query("DELETE FROM sources WHERE id = %s", source_id)
    return {"deleted": True}


def instance(row: dict):
    sec = json.loads(secrets.decrypt(row["credential"])) if row.get("credential") else {}
    return KINDS[row["kind"]](row["config"], sec)


@router.post("/sources/{source_id}/query")
def query_source(source_id: int, body: dict):
    """Run a query in the source's own language (PromQL, LogQL, NRQL, KQL, SPL...)."""
    row = db.one("SELECT * FROM sources WHERE id = %s AND mode = 'pull'", source_id)
    if not row:
        raise HTTPException(404, "pull source not found")
    try:
        return {"result": instance(row).query(body["query"], int(body.get("minutes", 15)))}
    except SourceError as exc:
        raise HTTPException(400, str(exc))


@router.get("/events")
def list_events(active: bool = False, service: str | None = None, limit: int = 100):
    return db.query(
        "SELECT * FROM source_events WHERE (NOT %s OR (status = 'firing' AND active_until > now()))"
        " AND (%s::text IS NULL OR service = %s) ORDER BY last_seen DESC LIMIT %s",
        active, service, service, limit)


agent_router = APIRouter()


@agent_router.get("/agent/tracewise")
def download_agent():
    """The host agent is a single stdlib-only Python file."""
    if not os.path.exists(AGENT_FILE):
        raise HTTPException(404, "agent file not bundled with this install")
    return FileResponse(AGENT_FILE, media_type="text/x-python", filename="tracewise")


@agent_router.get("/agent/install.sh")
def install_script(request: Request):
    base = public_url(request)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(f"""#!/bin/sh
# Installs the Tracewise host agent (needs python3 >= 3.8).
set -e
DEST="${{TRACEWISE_BIN:-/usr/local/bin/tracewise}}"
curl -fsSL {base}/agent/tracewise -o "$DEST.tmp" && chmod +x "$DEST.tmp" && mv "$DEST.tmp" "$DEST"
echo "installed $DEST"
echo "next: tracewise login --url {base} --key <ingest key> && tracewise detect"
""")
