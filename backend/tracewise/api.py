"""HTTP API: telemetry and deploy ingest, incidents, health, topology, and a live event stream."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import config, connections, db, health
from .sources import receivers, router as sources_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.open_pool()
    yield
    db.pool.close()


app = FastAPI(title="Tracewise", lifespan=lifespan)
app.include_router(connections.router)
app.include_router(receivers.router)
app.include_router(sources_router.router)
app.include_router(sources_router.agent_router)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def check_key(key: str | None) -> None:
    if config.INGEST_KEY and key != config.INGEST_KEY:
        raise HTTPException(401, "invalid ingest key")


def ts(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=timezone.utc)


@app.get("/healthz")
def healthz():
    db.one("SELECT 1")
    return {"ok": True}


@app.post("/v1/ingest/telemetry")
def ingest_telemetry(body: dict, x_ingest_key: str | None = Header(None)):
    check_key(x_ingest_key)
    service, at = body["service"], ts(body["ts"])
    db.query(
        "INSERT INTO services (name, current_sha) VALUES (%s, %s)"
        " ON CONFLICT (name) DO UPDATE SET current_sha = EXCLUDED.current_sha, last_seen = now()",
        service, body.get("sha"))
    db.query(
        "INSERT INTO metric_points (service, ts, sha, count, errors, p50_ms, p95_ms, max_ms)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        service, at, body.get("sha"), body["count"], body["errors"], body["p50_ms"],
        body["p95_ms"], body["max_ms"])
    for edge in body.get("edges", []):
        db.query(
            "INSERT INTO service_edges (src, dst, calls, errors) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (src, dst) DO UPDATE SET calls = service_edges.calls + EXCLUDED.calls,"
            " errors = service_edges.errors + EXCLUDED.errors, last_seen = now()",
            service, edge["to"], edge["calls"], edge["errors"])
        db.query(
            "INSERT INTO edge_points (src, dst, ts, calls, errors, avg_ms) VALUES (%s, %s, %s, %s, %s, %s)",
            service, edge["to"], at, edge["calls"], edge["errors"],
            edge["latency_ms"] / max(edge["calls"], 1))
    for entry in body.get("logs", []):
        extra = {k: v for k, v in entry.items()
                 if k not in ("ts", "level", "message", "route", "status", "trace")}
        db.query(
            "INSERT INTO log_events (service, ts, sha, level, message, route, status, trace, fields)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            service, ts(entry["ts"]), body.get("sha"), entry["level"], entry["message"],
            entry.get("route"), entry.get("status"), entry.get("trace"), db.jsonb(extra))
    return {"ok": True}


@app.post("/v1/ingest/deploys")
def ingest_deploy(body: dict, x_ingest_key: str | None = Header(None)):
    check_key(x_ingest_key)
    row = db.one(
        "INSERT INTO deploys (service, sha, prev_sha, author, author_email, message, committed_at,"
        " actor, reason, deployed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        body["service"], body["sha"], body.get("prev_sha"), body.get("author"),
        body.get("author_email"), body.get("message"), body.get("committed_at"), body.get("actor"),
        body.get("reason"), ts(body["deployed_at"]))
    db.notify("system_events", {"type": "deploy", "deploy_id": row["id"], **body})
    return {"id": row["id"]}


@app.get("/v1/health")
def service_health():
    return health.snapshot()


@app.get("/v1/topology")
def topology():
    edges = db.query("SELECT src, dst, calls, errors, last_seen FROM service_edges ORDER BY src, dst")
    services = db.query("SELECT name, current_sha, last_seen FROM services ORDER BY name")
    return {"services": services, "edges": edges}


@app.get("/v1/deploys")
def list_deploys(limit: int = 50):
    return db.query("SELECT * FROM deploys ORDER BY deployed_at DESC LIMIT %s", limit)


@app.get("/v1/incidents")
def list_incidents(limit: int = 50):
    return db.query(
        "SELECT i.*, r.turns, r.cost_usd, r.input_tokens, r.output_tokens FROM incidents i"
        " LEFT JOIN agent_runs r ON r.incident_id = i.id ORDER BY i.id DESC LIMIT %s", limit)


@app.get("/v1/incidents/{incident_id}")
def get_incident(incident_id: int):
    incident = db.one(
        "SELECT i.*, r.turns, r.cost_usd, r.input_tokens, r.output_tokens FROM incidents i"
        " LEFT JOIN agent_runs r ON r.incident_id = i.id WHERE i.id = %s", incident_id)
    if not incident:
        raise HTTPException(404, "incident not found")
    incident["steps"] = db.query(
        "SELECT * FROM incident_steps WHERE incident_id = %s ORDER BY id", incident_id)
    incident["actions"] = db.query(
        "SELECT * FROM actions WHERE incident_id = %s ORDER BY id", incident_id)
    return incident


@app.post("/v1/scenarios")
def start_scenario(body: dict):
    return db.one("INSERT INTO scenario_runs (name) VALUES (%s) RETURNING *", body["name"])


@app.patch("/v1/scenarios/{run_id}")
def finish_scenario(run_id: int, body: dict):
    return db.one("UPDATE scenario_runs SET ended_at = now(), result = %s WHERE id = %s RETURNING *",
                  db.jsonb(body.get("result", {})), run_id)


@app.get("/v1/scenarios")
def list_scenarios():
    return db.query("SELECT * FROM scenario_runs ORDER BY id DESC LIMIT 100")


@app.get("/v1/memories")
def list_memories():
    return db.query("SELECT id, incident_id, services, symptoms, root_cause, fix, outcome, created_at"
                    " FROM memories ORDER BY id DESC")


@app.get("/v1/stream")
async def stream():
    """Server-sent events: new timeline steps and deploys, as they happen."""

    async def events():
        conn = await psycopg.AsyncConnection.connect(config.DATABASE_URL, autocommit=True)
        try:
            await conn.execute("LISTEN incident_events")
            await conn.execute("LISTEN system_events")
            yield "retry: 2000\n\n"
            gen = conn.notifies()
            while True:
                try:
                    note = await asyncio.wait_for(anext(gen), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                payload = json.loads(note.payload)
                if payload.get("type") == "step":
                    payload["step"] = db.one("SELECT * FROM incident_steps WHERE id = %s",
                                             payload["step_id"])
                yield f"event: {payload['type']}\ndata: {json.dumps(payload, default=str)}\n\n"
        finally:
            await conn.close()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
