"""HTTP API: telemetry and deploy ingest, incidents, health, topology, and a live event stream."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from . import auth, config, connections, db, health, projects, tenancy, workspaces
from .sources import receivers, router as sources_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.open_pool()
    yield
    db.pool.close()


app = FastAPI(title="Tracewise", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(projects.router)
app.include_router(connections.router)
app.include_router(receivers.router)
app.include_router(sources_router.router)
app.include_router(sources_router.agent_router)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Anyone may call these: sign-in and invite previews.
PUBLIC = ("/v1/auth/otp", "/v1/auth/oauth", "/v1/auth/providers", "/v1/auth/logout", "/v1/invites/preview")
# Telemetry in: needs a project ingest key, which also decides the project.
INGEST = ("/v1/ingest",)
# A signed-in user without a workspace (or project) may still use these.
ACCOUNT = ("/v1/auth", "/v1/workspaces", "/v1/invites")
# Workspace-level settings, not tied to one project.
WORKSPACE_LEVEL = ACCOUNT + ("/v1/connections", "/v1/projects")


def deny(status: int, detail: str, code: str | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail, **({"code": code} if code else {})}, status_code=status)


@app.middleware("http")
async def access(request, call_next):
    """Who is calling, which workspace and project they act in, and whether they may."""
    path = request.url.path
    if not path.startswith("/v1/") or path.startswith(PUBLIC) or request.method == "OPTIONS":
        return await call_next(request)
    if path.startswith(INGEST):
        ctx = await run_in_threadpool(auth.service_context, request)
        if not ctx:
            return deny(401, "Invalid or missing ingest key.")
        request.state.auth = ctx
        return await call_next(request)
    ctx = await run_in_threadpool(auth.resolve, request)
    if not ctx:
        ctx = await run_in_threadpool(auth.service_context, request)
        if ctx and path.startswith(WORKSPACE_LEVEL):
            return deny(403, "Ingest keys can't manage accounts, workspaces or coding agents.")
    if not ctx:
        return deny(401, "Sign in required.", "unauthenticated")
    if not ctx["workspace"] and not path.startswith(ACCOUNT):
        return deny(403, "Create or join a workspace first.", "no_workspace")
    if not ctx.get("project") and not path.startswith(WORKSPACE_LEVEL):
        return deny(403, "Create a project first.", "no_project")
    if request.method not in ("GET", "HEAD") and not path.startswith(ACCOUNT):
        needed = "admin" if path.startswith(("/v1/connections", "/v1/sources", "/v1/projects")) else "member"
        if auth.rank(ctx["role"]) < auth.rank(needed):
            return deny(403, f"You need to be {needed} or above to do that.")
    request.state.auth = ctx
    return await call_next(request)


def pid(request: Request) -> int:
    return request.state.auth["project"]["id"]


def ts(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=timezone.utc)


@app.get("/healthz")
def healthz():
    db.one("SELECT 1")
    return {"ok": True}


@app.post("/v1/ingest/telemetry")
def ingest_telemetry(body: dict, request: Request):
    """Native telemetry (request metrics, error logs and calls to other services) from one service."""
    from .sources.model import store
    service, at = body["service"], ts(body["ts"])
    edges = [{"src": service, "dst": e["to"], "calls": e["calls"], "errors": e["errors"],
              "avg_ms": e["latency_ms"] / max(e["calls"], 1), "ts": at} for e in body.get("edges", [])]
    logs = [{"service": service, "ts": ts(e["ts"]), "sha": body.get("sha"), "level": e["level"],
             "message": e["message"], "route": e.get("route"), "status": e.get("status"), "trace": e.get("trace"),
             "fields": {k: v for k, v in e.items() if k not in ("ts", "level", "message", "route", "status", "trace")}}
            for e in body.get("logs", [])]
    metric = {"service": service, "ts": at, "sha": body.get("sha"), "count": body["count"],
              "errors": body["errors"], "p50_ms": body["p50_ms"], "p95_ms": body["p95_ms"], "max_ms": body["max_ms"]}
    store(None, pid(request), metrics=[metric], edges=edges, logs=logs)
    return {"ok": True}


@app.post("/v1/ingest/deploys")
def ingest_deploy(body: dict, request: Request):
    from .sources.model import store
    store(body.get("actor"), pid(request), deploys=[{**body, "deployed_at": ts(body["deployed_at"])}])
    return {"ok": True}


@app.get("/v1/health")
def service_health(request: Request):
    return health.snapshot(pid(request))


@app.get("/v1/topology")
def topology(request: Request):
    p = pid(request)
    edges = db.query("SELECT src, dst, calls, errors, last_seen FROM service_edges WHERE project_id = %s"
                     " ORDER BY src, dst", p)
    services = db.query("SELECT name, current_sha, last_seen FROM services WHERE project_id = %s ORDER BY name", p)
    return {"services": services, "edges": edges}


@app.get("/v1/deploys")
def list_deploys(request: Request, limit: int = 50):
    return db.query("SELECT * FROM deploys WHERE project_id = %s ORDER BY deployed_at DESC LIMIT %s",
                    pid(request), min(limit, 500))


@app.get("/v1/incidents")
def list_incidents(request: Request, limit: int = 50):
    return db.query(
        "SELECT i.*, r.turns, r.cost_usd, r.input_tokens, r.output_tokens FROM incidents i"
        " LEFT JOIN agent_runs r ON r.incident_id = i.id WHERE i.project_id = %s ORDER BY i.id DESC LIMIT %s",
        pid(request), min(limit, 500))


@app.get("/v1/incidents/{incident_id}")
def get_incident(incident_id: int, request: Request):
    incident = db.one(
        "SELECT i.*, r.turns, r.cost_usd, r.input_tokens, r.output_tokens FROM incidents i"
        " LEFT JOIN agent_runs r ON r.incident_id = i.id WHERE i.id = %s AND i.project_id = %s",
        incident_id, pid(request))
    if not incident:
        raise HTTPException(404, "incident not found")
    incident["steps"] = db.query("SELECT * FROM incident_steps WHERE incident_id = %s ORDER BY id", incident_id)
    incident["actions"] = db.query("SELECT * FROM actions WHERE incident_id = %s ORDER BY id", incident_id)
    return incident


@app.post("/v1/scenarios")
def start_scenario(body: dict, request: Request):
    return db.one("INSERT INTO scenario_runs (name, project_id) VALUES (%s, %s) RETURNING *", body["name"], pid(request))


@app.patch("/v1/scenarios/{run_id}")
def finish_scenario(run_id: int, body: dict, request: Request):
    return db.one("UPDATE scenario_runs SET ended_at = now(), result = %s WHERE id = %s AND project_id = %s"
                  " RETURNING *", db.jsonb(body.get("result", {})), run_id, pid(request))


@app.get("/v1/scenarios")
def list_scenarios(request: Request):
    return db.query("SELECT * FROM scenario_runs WHERE project_id = %s ORDER BY id DESC LIMIT 100", pid(request))


@app.get("/v1/memories")
def list_memories(request: Request):
    return db.query("SELECT id, incident_id, services, symptoms, root_cause, fix, outcome, created_at"
                    " FROM memories WHERE project_id = %s ORDER BY id DESC", pid(request))


def _project_of(payload: dict) -> int | None:
    if "project_id" in payload:
        return payload["project_id"]
    if payload.get("incident_id"):
        row = db.one("SELECT project_id FROM incidents WHERE id = %s", payload["incident_id"])
        return row and row["project_id"]
    if payload.get("job_id"):
        row = db.one("SELECT project_id FROM fix_jobs WHERE id = %s", payload["job_id"])
        return row and row["project_id"]
    return None


@app.get("/v1/stream")
async def stream(request: Request):
    """Server-sent events for this project: new timeline steps, incidents, deploys and alerts."""
    project = pid(request)

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
                if await run_in_threadpool(_project_of, payload) != project:
                    continue
                if payload.get("type") == "step":
                    payload["step"] = await run_in_threadpool(
                        db.one, "SELECT * FROM incident_steps WHERE id = %s", payload["step_id"])
                yield f"event: {payload['type']}\ndata: {json.dumps(payload, default=str)}\n\n"
        finally:
            await conn.close()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
