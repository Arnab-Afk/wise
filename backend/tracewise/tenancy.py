"""Multi-tenancy: projects own all telemetry and incidents; ingest keys decide the project.

migrate() upgrades a single-tenant database in place: existing data moves into a "Shopfront demo"
workspace and project, the legacy TW_INGEST_KEY becomes that project's key, and uniqueness rules
become per-project. It is idempotent and runs under an advisory lock, so every process can call it.
"""

import hashlib
import hmac
import logging
import os
import secrets as pysecrets
import time

from . import config

log = logging.getLogger("tracewise.tenancy")
_KEY = (os.environ.get("TW_SECRET_KEY") or config.INGEST_KEY or "tracewise-dev").encode()
DATA_TABLES = ("services", "service_edges", "metric_points", "edge_points", "log_events", "deploys",
               "incidents", "memories", "scenario_runs", "fix_jobs", "sources", "source_events")
DEMO_SLUG = "shopfront-demo"


def digest(value: str) -> str:
    return hmac.new(_KEY, value.encode(), hashlib.sha256).hexdigest()


def new_key() -> str:
    return "twk_" + pysecrets.token_urlsafe(30)


def _constraint_cols(cur, table: str, kind: str) -> list[tuple[str, list[str]]]:
    cur.execute("""SELECT c.conname, array_agg(a.attname ORDER BY k.ord) AS cols
                   FROM pg_constraint c CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum, ord)
                   JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                   WHERE c.conrelid = %s::regclass AND c.contype = %s GROUP BY c.conname""", (table, kind))
    return [(r["conname"], list(r["cols"])) for r in cur.fetchall()]


def _rekey(cur, table: str, kind: str, old_cols: list[str], new_cols: list[str], name: str) -> None:
    for conname, cols in _constraint_cols(cur, table, kind):
        if cols == new_cols:
            return
        if cols == old_cols:
            cur.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{conname}"')
    clause = "PRIMARY KEY" if kind == "p" else "UNIQUE"
    cur.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {clause} ({', '.join(new_cols)})")


def ensure_demo(cur) -> int | None:
    """The workspace and project that hold the Shopfront demo (and any pre-tenancy data)."""
    cur.execute("SELECT p.id FROM projects p JOIN workspaces w ON w.id = p.workspace_id"
                " WHERE w.slug = %s AND p.slug = 'shopfront'", (DEMO_SLUG,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute("INSERT INTO workspaces (name, slug) VALUES ('Shopfront demo', %s)"
                " ON CONFLICT (slug) DO UPDATE SET name = workspaces.name RETURNING id", (DEMO_SLUG,))
    ws = cur.fetchone()["id"]
    cur.execute("INSERT INTO projects (workspace_id, name, slug, description, deployer_url, repo_path, action_policy)"
                " VALUES (%s, 'Shopfront', 'shopfront', 'Seven-service demo store with a deployer', %s, %s, 'auto')"
                " RETURNING id", (ws, config.DEPLOYER_URL, config.SHOPFRONT_REPO))
    return cur.fetchone()["id"]


def migrate(conn) -> None:
    cur = conn.cursor()
    pending = False
    for t in DATA_TABLES:
        cur.execute(f"SELECT EXISTS (SELECT 1 FROM {t} WHERE project_id IS NULL) AS x")
        pending = pending or cur.fetchone()["x"]
    cur.execute("SELECT EXISTS (SELECT 1 FROM connections WHERE workspace_id IS NULL) AS x")
    pending = pending or cur.fetchone()["x"]
    demo = ensure_demo(cur) if (pending or config.INGEST_KEY) else None
    if pending:
        log.info("moving existing single-tenant data into the Shopfront demo project %s", demo)
        for t in DATA_TABLES:
            cur.execute(f"UPDATE {t} SET project_id = %s WHERE project_id IS NULL", (demo,))
        cur.execute("UPDATE connections SET workspace_id = (SELECT workspace_id FROM projects WHERE id = %s)"
                    " WHERE workspace_id IS NULL", (demo,))
    for t in DATA_TABLES:
        cur.execute(f"ALTER TABLE {t} ALTER COLUMN project_id SET NOT NULL")
    cur.execute("ALTER TABLE connections ALTER COLUMN workspace_id SET NOT NULL")
    _rekey(cur, "services", "p", ["name"], ["project_id", "name"], "services_project_pkey")
    _rekey(cur, "service_edges", "p", ["src", "dst"], ["project_id", "src", "dst"], "service_edges_project_pkey")
    _rekey(cur, "sources", "u", ["kind", "name"], ["project_id", "kind", "name"], "sources_project_kind_name")
    _rekey(cur, "source_events", "u", ["source", "fingerprint"], ["project_id", "source", "fingerprint"],
           "source_events_project_fingerprint")
    # Projects that existed before approvals act automatically, as they always did (once only:
    # an admin may switch them to approval later).
    cur.execute("SELECT 1 FROM schema_meta WHERE key = 'approval_backfill'")
    if not cur.fetchone():
        cur.execute("UPDATE projects SET action_policy = 'auto' WHERE created_at < now()")
        cur.execute("INSERT INTO schema_meta (key, value) VALUES ('approval_backfill', 'done')")
    if demo and config.INGEST_KEY:  # the legacy key keeps working, now scoped to the demo project
        cur.execute("INSERT INTO project_keys (project_id, name, prefix, key_hash) VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (key_hash) DO NOTHING",
                    (demo, "Shopfront runtime (TW_INGEST_KEY)", config.INGEST_KEY[:8], digest(config.INGEST_KEY)))


# ---------------------------------------------------------------- key lookup

_cache: dict[str, tuple[float, dict | None]] = {}


def project_for_key(key: str | None) -> dict | None:
    """The project an ingest key sends to (cached briefly), or None."""
    if not key:
        return None
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    from . import db
    row = db.one("SELECT p.id, p.name, p.slug, p.workspace_id, p.deployer_url, p.repo_path, k.id AS key_id,"
                 " w.name AS workspace_name, w.slug AS workspace_slug"
                 " FROM project_keys k JOIN projects p ON p.id = k.project_id JOIN workspaces w ON w.id = p.workspace_id"
                 " WHERE k.key_hash = %s AND k.revoked_at IS NULL", digest(key))
    if row:
        db.query("UPDATE project_keys SET last_used_at = now() WHERE id = %s"
                 " AND (last_used_at IS NULL OR last_used_at < now() - interval '1 minute')", row["key_id"])
    _cache[key] = (time.time() + 30, row)
    return row


def forget_keys() -> None:
    _cache.clear()
