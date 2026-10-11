"""The agent's tools. Each one returns a JSON-serialisable result or raises ToolError."""

import contextvars
import json
import subprocess
import time

import httpx

from .. import config, db, health

INVESTIGATE, PLAN, HYPOTHESIZE, ACT, FIX, VERIFY, FINISH = (
    "investigate", "plan", "hypothesize", "act", "fix", "verify", "finish")


class ToolError(Exception):
    pass


# The project the current incident belongs to; set by the agent loop for each run.
PROJECT: contextvars.ContextVar[dict] = contextvars.ContextVar("project")


def P() -> int:
    return PROJECT.get()["id"]


def repo() -> str:
    path = PROJECT.get().get("repo_path")
    if not path:
        raise ToolError("This project has no code repository connected, so code tools aren't available. "
                        "Use telemetry, and say in the handover which code you'd look at.")
    return path


def deployer_url() -> str:
    url = PROJECT.get().get("deployer_url")
    if not url:
        raise ToolError("Tracewise can't deploy, roll back, restart or flip flags in this project yet (no deploy "
                        "integration). Investigate fully and escalate with the exact command you'd run.")
    return url


# ---------- helpers ----------

def git(*args: str, max_chars: int = 12000) -> str:
    proc = subprocess.run(["git", "-C", repo(), *args], capture_output=True,
                          text=True, timeout=30)
    if proc.returncode != 0:
        raise ToolError(proc.stderr.strip()[:500])
    return proc.stdout[:max_chars]


def entire_graph(*args: str, max_chars: int = 12000) -> str:
    try:
        proc = subprocess.run(["entire", "graph", *args], cwd=repo(),
                              capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise ToolError("entire CLI is not installed in this environment")
    except subprocess.TimeoutExpired:
        raise ToolError("entire graph timed out")
    out = (proc.stdout or proc.stderr).strip()
    if proc.returncode != 0 and not proc.stdout:
        raise ToolError(f"entire graph {' '.join(args)} failed: {out[:800]}")
    return out[:max_chars]


def entire_checkpoint(ref: str) -> str:
    """The agent session behind a commit: its intent, files and transcript."""
    try:
        proc = subprocess.run(["entire", "checkpoint", "explain", ref], cwd=repo(),
                              capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return "(entire CLI not installed)"
    return (proc.stdout or proc.stderr).strip()[:4000]


def deployer(method: str, path: str, body: dict | None = None) -> dict:
    try:
        resp = httpx.request(method, f"{deployer_url()}{path}", json=body, timeout=60)
    except httpx.HTTPError as exc:
        raise ToolError(f"deployer unreachable: {exc}")
    if resp.status_code >= 400:
        raise ToolError(f"deployer said {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def short(sha: str | None) -> str | None:
    return sha[:10] if sha else sha


# ---------- investigate ----------

def get_service_health(ctx, service: str | None = None, window_seconds: int = 30):
    return health.snapshot(P(), max(10, min(window_seconds, 600)), service)


def get_metrics(ctx, service: str, minutes: int = 10):
    rows = db.query(
        """SELECT to_timestamp(floor(extract(epoch FROM ts) / 20) * 20) AS bucket,
                  sum(count) AS requests, sum(errors) AS errors,
                  round((sum(p95_ms * count) / nullif(sum(count), 0))::numeric, 1) AS p95_ms,
                  max(sha) AS sha
           FROM metric_points WHERE project_id = %s AND service = %s AND ts > now() - make_interval(mins => %s)
           GROUP BY 1 ORDER BY 1""", P(), service, max(1, min(minutes, 60)))
    return [{"t": r["bucket"].strftime("%H:%M:%S"), "requests": int(r["requests"]),
             "error_rate": round(r["errors"] / r["requests"], 3) if r["requests"] else 0,
             "p95_ms": float(r["p95_ms"]) if r["p95_ms"] is not None else None,
             "sha": short(r["sha"])} for r in rows]


def search_logs(ctx, service: str | None = None, contains: str | None = None,
                minutes: int = 10, limit: int = 15, min_level: str = "warning"):
    rows = db.query(
        """SELECT service, level, message, route, status, sha, source, sum(count) AS n,
                  max(ts) AS last_seen, min(ts) AS first_seen,
                  (array_agg(trace ORDER BY ts DESC) FILTER (WHERE trace IS NOT NULL))[1] AS sample_trace
           FROM log_events
           WHERE project_id = %s AND ts > now() - make_interval(mins => %s)
             AND (%s::text IS NULL OR service = %s)
             AND (%s::text IS NULL OR message ILIKE '%%' || %s || '%%' OR trace ILIKE '%%' || %s || '%%')
             AND level = ANY(%s)
           GROUP BY service, level, message, route, status, sha, source ORDER BY n DESC LIMIT %s""",
        P(), max(1, min(minutes, 120)), service, service, contains, contains, contains,
        LEVELS[LEVELS.index(min_level if min_level in LEVELS else "warning"):],
        max(1, min(limit, 40)))
    for r in rows:
        r["sha"] = short(r["sha"])
        if r["sample_trace"]:
            r["sample_trace"] = r["sample_trace"][-1500:]
    return rows


LEVELS = ["debug", "info", "warning", "error", "critical"]


def list_events(ctx, service: str | None = None, minutes: int = 60):
    """Alerts, crashes, restarts, OOM kills and failed checks reported by connected sources."""
    rows = db.query(
        """SELECT service, source, kind, severity, status, title, started_at, last_seen,
                  (status = 'firing' AND active_until > now()) AS active, detail
           FROM source_events
           WHERE project_id = %s AND last_seen > now() - make_interval(mins => %s) AND (%s::text IS NULL OR service = %s)
           ORDER BY last_seen DESC LIMIT 40""", P(), max(1, min(minutes, 1440)), service, service)
    for r in rows:
        r["detail"] = json.dumps(r["detail"], default=str)[:600]
    return rows


def list_sources(ctx):
    """Connected telemetry sources, and for pull sources the query language query_source takes."""
    from ..sources.pull import KINDS
    rows = db.query("SELECT id, kind, name, mode, status, last_received_at, items_received FROM sources"
                    " WHERE project_id = %s AND enabled ORDER BY mode, kind", P())
    for r in rows:
        cls = KINDS.get(r["kind"]) if r["mode"] == "pull" else None
        if cls and cls.query_language:
            r["query_language"], r["example"] = cls.query_language, cls.query_example
    return rows


def query_source(ctx, source: str, query: str, minutes: int = 15):
    """Run a query against a connected tool (Prometheus, Loki, Datadog...) in its own language."""
    from ..collector import instance
    from ..sources.pull import SourceError
    row = db.one("SELECT * FROM sources WHERE project_id = %s AND mode = 'pull' AND (name = %s OR kind = %s OR id::text = %s)"
                 " ORDER BY (name = %s) DESC LIMIT 1", P(), source, source, source, source)
    if not row:
        raise ToolError(f"No pull source called {source!r}; call list_sources")
    try:
        result = instance(row).query(query, max(1, min(int(minutes), 1440)))
    except SourceError as exc:
        raise ToolError(f"{row['kind']} said: {exc}")
    text = json.dumps(result, default=str)
    return text if len(text) < 14000 else text[:14000] + " …(truncated; narrow the query)"


def get_dependencies(ctx, service: str):
    edges = db.query(
        """SELECT e.src, e.dst,
                  coalesce(sum(p.calls), 0) AS calls_last_min,
                  coalesce(sum(p.errors), 0) AS errors_last_min,
                  round(avg(p.avg_ms)::numeric, 1) AS avg_ms
           FROM service_edges e
           LEFT JOIN edge_points p ON p.project_id = e.project_id AND p.src = e.src AND p.dst = e.dst
                                   AND p.ts > now() - interval '60 seconds'
           WHERE e.project_id = %s
           GROUP BY e.src, e.dst""", P())
    callers: dict[str, list[str]] = {}
    for e in edges:
        callers.setdefault(e["dst"], []).append(e["src"])
    # Everything that (transitively) depends on this service is in its blast radius.
    blast, stack = set(), [service]
    while stack:
        for caller in callers.get(stack.pop(), []):
            if caller not in blast:
                blast.add(caller)
                stack.append(caller)

    def fmt(e):
        return {"from": e["src"], "to": e["dst"], "calls_last_min": int(e["calls_last_min"]),
                "error_rate_last_min": round(e["errors_last_min"] / e["calls_last_min"], 3)
                if e["calls_last_min"] else None,
                "avg_ms": float(e["avg_ms"]) if e["avg_ms"] is not None else None}

    return {"service": service,
            "calls": [fmt(e) for e in edges if e["src"] == service],
            "called_by": [fmt(e) for e in edges if e["dst"] == service],
            "blast_radius": sorted(blast)}


def list_recent_deploys(ctx, service: str | None = None, minutes: int = 120):
    rows = db.query(
        """SELECT id, service, sha, prev_sha, author, message, actor, reason, deployed_at
           FROM deploys WHERE project_id = %s AND deployed_at > now() - make_interval(mins => %s)
             AND (%s::text IS NULL OR service = %s) AND coalesce(actor, '') <> 'bootstrap'
           ORDER BY deployed_at DESC LIMIT 20""", P(), max(1, min(minutes, 1440)), service, service)
    for r in rows:
        r["sha"], r["prev_sha"] = short(r["sha"]), short(r["prev_sha"])
        r["minutes_ago"] = round((time.time() - r.pop("deployed_at").timestamp()) / 60, 1)
    return rows


def inspect_commit(ctx, sha: str):
    """The commit's message, diff, and Entire Graph's entity-level view of what changed."""
    show = git("show", "--stat", "--format=commit %H%nAuthor: %an <%ae>%nDate: %cI%n%n%B", sha,
               max_chars=3000)
    diff = git("show", "--format=", sha, max_chars=6000)
    try:
        entities = entire_graph("commit", sha, "--repo", ".", "--max-seconds", "60", max_chars=5000)
    except ToolError as exc:
        entities = f"(unavailable: {exc})"
    trailer = next((line.split(":", 1)[1].strip() for line in show.splitlines()
                    if line.strip().lower().startswith("entire-checkpoint:")), None)
    if trailer:
        checkpoint = entire_checkpoint(sha)
    else:
        checkpoint = "No Entire checkpoint: this commit wasn't made in a tracked agent session."
    return {"summary": show, "diff": diff, "entire_graph_changes": entities,
            "entire_checkpoint": checkpoint}


def code_search(ctx, query: str):
    return entire_graph("search", "--query", query, "--repo", ".", "--format", "agent",
                        "--profile", "full", "--head", "--top-k", "6")


def code_impact(ctx, symbol: str):
    return entire_graph("impact", "--symbol", symbol, "--repo", ".", "--format", "text", "--head")


def explain_failure(ctx, text: str):
    """Resolve the symbols named in a stack trace or error message to code locations."""
    try:
        proc = subprocess.run(["entire", "graph", "explain", "--repo", ".", "--format", "agent",
                               "--head", "--no-echo"], input=text, cwd=repo(),
                              capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise ToolError("entire CLI is not installed in this environment")
    return (proc.stdout or proc.stderr)[:10000] or "No symbols resolved."


def read_code(ctx, path: str, ref: str = "HEAD", start_line: int = 1, end_line: int = 200):
    text = git("show", f"{ref}:{path}", max_chars=200_000)
    lines = text.splitlines()
    start = max(1, start_line)
    chunk = lines[start - 1:max(start, min(end_line, start + 400))]
    return "\n".join(f"{i:4d}  {line}" for i, line in enumerate(chunk, start))


def search_memory(ctx, query: str):
    rows = db.query(
        """SELECT id, incident_id, services, symptoms, root_cause, fix, outcome, created_at,
                  ts_rank(search, websearch_to_tsquery('english', %s)) AS rank
           FROM memories
           WHERE project_id = %s AND (search @@ websearch_to_tsquery('english', %s)
              OR symptoms %% %s OR root_cause %% %s)
           ORDER BY rank DESC, id DESC LIMIT 5""", query, P(), query, query, query)
    if not rows:
        rows = db.query("SELECT id, incident_id, services, symptoms, root_cause, fix, outcome,"
                        " created_at FROM memories WHERE project_id = %s AND services && %s ORDER BY id DESC LIMIT 3",
                        P(), ctx["incident"]["services"])
    return rows or "No similar past incidents."


# ---------- plan / hypothesize ----------

def record_plan(ctx, goal: str, steps: list[str]):
    return {"recorded": True, "steps": len(steps)}


def record_hypotheses(ctx, hypotheses: list[dict]):
    return {"recorded": True, "count": len(hypotheses)}


# ---------- act ----------

def _guard_action(ctx) -> None:
    incident_id = ctx["incident"]["id"]
    done = db.query("SELECT kind, created_at FROM actions WHERE incident_id = %s AND status = 'done'"
                    " ORDER BY id", incident_id)
    if len(done) >= config.MAX_ACTIONS:
        raise ToolError(f"Action budget used up ({config.MAX_ACTIONS}). Escalate instead.")
    if done:
        verified = db.one("SELECT 1 FROM incident_steps WHERE incident_id = %s AND kind = 'verify'"
                          " AND ts > %s", incident_id, done[-1]["created_at"])
        if not verified:
            raise ToolError("Verify the previous action with verify_recovery before taking another.")


def _run_action(ctx, kind: str, target: str, params: dict, fn) -> dict:
    key = f"{ctx['incident']['id']}:{ctx['tool_use_id']}"
    existing = db.one("SELECT status, result FROM actions WHERE idempotency_key = %s", key)
    if existing and existing["status"] == "done":
        return {**existing["result"], "note": "already applied (resumed run)"}
    _guard_action(ctx)
    db.query("INSERT INTO actions (incident_id, idempotency_key, kind, target, params, status)"
             " VALUES (%s, %s, %s, %s, %s, 'running') ON CONFLICT (idempotency_key) DO NOTHING",
             ctx["incident"]["id"], key, kind, target, db.jsonb(params))
    try:
        result = fn()
    except ToolError as exc:
        db.query("UPDATE actions SET status = 'failed', result = %s WHERE idempotency_key = %s",
                 db.jsonb({"error": str(exc)}), key)
        raise
    db.query("UPDATE actions SET status = 'done', result = %s WHERE idempotency_key = %s",
             db.jsonb(result), key)
    return result


def set_flag(ctx, name: str, value, reason: str):
    allowed = {"payments_use_backup": bool}
    if name not in allowed:
        raise ToolError(f"Unknown or protected flag {name!r}. Allowed: {sorted(allowed)}")
    return _run_action(ctx, "set_flag", name, {"value": value, "reason": reason},
                       lambda: deployer("PUT", "/flags", {name: allowed[name](value)}))


def rollback_service(ctx, service: str, reason: str, to_sha: str | None = None):
    def go():
        body = {"service": service, "actor": "tracewise", "reason": reason}
        if to_sha:
            body["to_sha"] = to_sha
        r = deployer("POST", "/rollback", body)
        return {"service": service, "now_running": short(r["sha"]), "was": short(r["prev_sha"])}
    return _run_action(ctx, "rollback", service, {"reason": reason, "to_sha": to_sha}, go)


def restart_service(ctx, service: str, reason: str):
    return _run_action(ctx, "restart", service, {"reason": reason},
                       lambda: deployer("POST", "/restart", {"service": service}))


# ---------- fix forward (connected coding agents) ----------

def request_code_fix(ctx, service: str, problem: str, base_sha: str | None = None):
    """Ask the team's connected coding agent to write a tested fix on its own branch, and wait."""
    repo()  # a fix needs the code
    conn = db.one("SELECT id, provider, status FROM connections WHERE workspace_id = %s"
                  " ORDER BY is_default DESC, id LIMIT 1", PROJECT.get()["workspace_id"])
    if not conn:
        raise ToolError("No coding agent is connected. A teammate can connect Claude or Cursor in "
                        "Settings; until then, keep the rollback and escalate the code fix.")
    if conn["status"] == "failed":
        raise ToolError("The connected coding agent's key failed its check; can't start a fix.")
    base = git("rev-parse", base_sha or "HEAD").strip()
    incident = ctx["incident"]
    existing = db.one("SELECT id FROM fix_jobs WHERE incident_id = %s AND service = %s"
                      " AND status IN ('queued', 'running', 'ready') ORDER BY id DESC LIMIT 1",
                      incident["id"], service)
    job_id = existing["id"] if existing else db.one(
        "INSERT INTO fix_jobs (project_id, incident_id, connection_id, provider, service, task, base_sha, branch)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        P(), incident["id"], conn["id"], conn["provider"], service, problem, base,
        f"tracewise/fix-incident-{incident['id']}-{service}")["id"]
    deadline = time.time() + 1080
    while time.time() < deadline:
        job = db.one("SELECT * FROM fix_jobs WHERE id = %s", job_id)
        if job["status"] in ("ready", "failed"):
            return {"job_id": job_id, "status": job["status"], "agent": job["provider"],
                    "branch": job["branch"], "commit": short(job["commit_sha"]),
                    "tests_passed": job["tests_passed"], "entire_checkpoint": job["checkpoint_id"],
                    "summary": job["agent_summary"], "error": job["error"],
                    "diff": (job["diff"] or "")[:5000],
                    "test_output_tail": (job["test_output"] or "")[-800:]}
        time.sleep(5)
        ctx["heartbeat"]()
    raise ToolError(f"Fix job {job_id} is still running after 18 minutes; escalate with its branch.")


def deploy_fix(ctx, job_id: int, reason: str):
    job = db.one("SELECT * FROM fix_jobs WHERE id = %s AND incident_id = %s", job_id,
                 ctx["incident"]["id"])
    if not job:
        raise ToolError(f"Fix job {job_id} doesn't belong to this incident.")
    if job["status"] != "ready" or not job["tests_passed"]:
        raise ToolError("Only a fix whose tests passed can be deployed.")
    if not config.AUTO_DEPLOY_FIXES:
        return {"deployed": False, "branch": job["branch"],
                "note": "Auto-deploy of fixes is off: the fix is waiting on its branch for review."}

    def go():
        # Fast-forward main so the next normal deploy doesn't bring the bug back.
        merged = subprocess.run(["git", "-C", repo(), "merge", "--ff-only",
                                 job["branch"]], capture_output=True, text=True).returncode == 0
        r = deployer("POST", "/deploy", {"service": job["service"], "ref": job["commit_sha"],
                                         "actor": "tracewise", "reason": reason})
        return {"service": job["service"], "now_running": short(r["sha"]), "merged_to_main": merged}
    return _run_action(ctx, "deploy_fix", job["service"], {"job_id": job_id, "reason": reason}, go)


# ---------- verify ----------

def verify_recovery(ctx, services: list[str], seconds: int = 45):
    """Watch the services for a while; recovered only if every check in the last 30s is healthy."""
    seconds = max(30, min(seconds, 180))
    deadline, samples = time.time() + seconds, []
    while time.time() < deadline:
        time.sleep(5)
        snap = {s["service"]: s for s in health.snapshot(P(), 15)}
        samples.append({svc: snap.get(svc, {}).get("status", "unknown") for svc in services})
        ctx["heartbeat"]()
    tail = samples[-6:]
    recovered = all(status == "healthy" for sample in tail for status in sample.values())
    final = [s for s in health.snapshot(P(), 20) if s["service"] in services]
    return {"recovered": recovered, "watched_seconds": seconds,
            "status_over_time": samples, "final": final}


# ---------- finish ----------

def resolve_incident(ctx, title: str, summary: str, root_cause: str, fix: str,
                     evidence: list[dict], lesson: str):
    last = db.one("SELECT data FROM incident_steps WHERE incident_id = %s AND kind = 'verify'"
                  " ORDER BY id DESC LIMIT 1", ctx["incident"]["id"])
    if not last or not last["data"].get("result", {}).get("recovered"):
        raise ToolError("Can't resolve: the last verify_recovery did not show recovery.")
    return {"resolved": True}


def escalate(ctx, reason: str, handover: str):
    return {"escalated": True}


# ---------- registry ----------

S = lambda **props: {"type": "object", "properties": props,  # noqa: E731
                     "required": [k for k, v in props.items() if not v.pop("optional", False)],
                     "additionalProperties": False}
STR = lambda d, **kw: {"type": "string", "description": d, **kw}  # noqa: E731
INT = lambda d, **kw: {"type": "integer", "description": d, **kw}  # noqa: E731

TOOLS = {
    "get_service_health": (INVESTIGATE, get_service_health,
        "Current health of every service (or one) versus its own 15-minute baseline: requests, "
        "error rate, p95 latency, status (healthy/erroring/slow/silent) and running commit.",
        S(service=STR("Service name; omit for all", optional=True),
          window_seconds=INT("Look-back window, 10-600", optional=True))),
    "get_metrics": (INVESTIGATE, get_metrics,
        "A service's request rate, error rate and p95 in 20-second buckets, with the commit that "
        "was running. Use it to see exactly when a problem started.",
        S(service=STR("Service name"), minutes=INT("How far back, 1-60", optional=True))),
    "search_logs": (INVESTIGATE, search_logs,
        "Recent logs from every source (services, host agents, Loki, Datadog, OTLP...), grouped by "
        "message with counts, first/last seen, which source sent them and a sample stack trace.",
        S(service=STR("Service name", optional=True),
          contains=STR("Text the message or stack trace must contain", optional=True),
          minutes=INT("How far back, 1-120", optional=True),
          limit=INT("Max groups, 1-40", optional=True),
          min_level=STR("Lowest level to include: debug, info, warning (default), error, critical",
                        optional=True))),
    "list_events": (INVESTIGATE, list_events,
        "Alerts (Alertmanager, Grafana, Datadog, PagerDuty, CloudWatch...), crashes, restarts, OOM "
        "kills and failed health checks reported by connected sources, with whether each is active.",
        S(service=STR("Service name", optional=True), minutes=INT("How far back, 1-1440", optional=True))),
    "list_sources": (INVESTIGATE, list_sources,
        "The telemetry sources connected to Tracewise and the query language each pull source accepts.",
        S()),
    "query_source": (INVESTIGATE, query_source,
        "Query a connected tool directly in its own language (PromQL for Prometheus, LogQL for Loki, "
        "Lucene for Elasticsearch, NRQL for New Relic, Logs Insights for CloudWatch, KQL for Azure, SPL "
        "for Splunk...) when the data you need isn't in Tracewise's own tables.",
        S(source=STR("Source name, kind or id from list_sources"), query=STR("The query"),
          minutes=INT("Time range in minutes, 1-1440", optional=True))),
    "get_dependencies": (INVESTIGATE, get_dependencies,
        "Which services this one calls and is called by, with live per-edge error rates, and its "
        "blast radius (everything that depends on it).",
        S(service=STR("Service name"))),
    "list_recent_deploys": (INVESTIGATE, list_recent_deploys,
        "Recent deploys (commit, previous commit, author, message, who deployed, minutes ago).",
        S(service=STR("Service name", optional=True),
          minutes=INT("How far back, 1-1440", optional=True))),
    "inspect_commit": (INVESTIGATE, inspect_commit,
        "Show a commit: message, author, diff, Entire Graph's list of changed symbols, and the Entire "
        "checkpoint (the agent session that produced it) if one exists.",
        S(sha=STR("Commit SHA (short is fine)"))),
    "code_search": (INVESTIGATE, code_search,
        "Entire Graph ranked code search over the project repo from a plain-language description.",
        S(query=STR("What you're looking for"))),
    "code_impact": (INVESTIGATE, code_impact,
        "Entire Graph blast radius for changing a symbol: callers, callees, type users, co-changed files.",
        S(symbol=STR("Symbol name, e.g. compute_total"))),
    "explain_failure": (INVESTIGATE, explain_failure,
        "Give Entire Graph a stack trace or error text; it resolves the named symbols to file:line.",
        S(text=STR("Stack trace or error output"))),
    "read_code": (INVESTIGATE, read_code,
        "Read a file from the project repo at a ref, with line numbers.",
        S(path=STR("Repo-relative path"), ref=STR("Git ref, default HEAD", optional=True),
          start_line=INT("First line", optional=True), end_line=INT("Last line", optional=True))),
    "search_memory": (INVESTIGATE, search_memory,
        "Search past resolved incidents: symptoms, root cause, fix and whether the fix worked.",
        S(query=STR("Symptoms or suspected cause"))),
    "record_plan": (PLAN, record_plan,
        "Write down your goal and the steps you intend to take. Call this first, and again if you re-plan.",
        S(goal=STR("What 'fixed' means for this incident"),
          steps={"type": "array", "items": {"type": "string"}, "description": "Ordered steps"})),
    "record_hypotheses": (HYPOTHESIZE, record_hypotheses,
        "Record ranked candidate causes, each with its evidence, confidence and the action that would test it.",
        S(hypotheses={"type": "array", "items": S(
            cause=STR("The suspected cause"), evidence=STR("What points to it"),
            confidence={"type": "number", "description": "0-1"},
            test=STR("The least risky action that would confirm or rule it out"))})),
    "set_flag": (ACT, set_flag,
        "Flip a runtime feature flag. Available: payments_use_backup (true routes card payments to "
        "the backup processor instead of the bank).",
        S(name=STR("Flag name"), value={"type": "boolean", "description": "New value"},
          reason=STR("Why, citing evidence"))),
    "rollback_service": (ACT, rollback_service,
        "Redeploy a service's previous commit (or a given one).",
        S(service=STR("Service name"), reason=STR("Why, citing evidence"),
          to_sha=STR("Specific commit to roll back to", optional=True))),
    "restart_service": (ACT, restart_service,
        "Restart a service on the same commit.",
        S(service=STR("Service name"), reason=STR("Why, citing evidence"))),
    "request_code_fix": (FIX, request_code_fix,
        "Ask the team's connected coding agent (Claude or Cursor) to write a fix plus a regression "
        "test on its own branch. Waits for it (up to 18 min) and returns the diff, the test result "
        "(run independently by Tracewise) and the Entire checkpoint of the agent's session. Use it "
        "after production is stable, when the cause was a code bug in a change worth keeping.",
        S(service=STR("Service whose code needs fixing"),
          problem=STR("The bug, its evidence (error, stack trace, file:line) and the faulty commit"),
          base_sha=STR("Commit to branch from (usually the faulty commit); default main", optional=True))),
    "deploy_fix": (ACT, deploy_fix,
        "Deploy a fix from request_code_fix whose tests passed, then verify it.",
        S(job_id=INT("Fix job id"), reason=STR("Why it's safe to deploy"))),
    "verify_recovery": (VERIFY, verify_recovery,
        "Watch services for 30-180 seconds after an action. Recovered only if they stay healthy for the "
        "last 30 seconds. Required after every action and before resolving.",
        S(services={"type": "array", "items": {"type": "string"}, "description": "Services to watch"},
          seconds=INT("How long to watch, 30-180", optional=True))),
    "resolve_incident": (FINISH, resolve_incident,
        "Close the incident after verify_recovery showed recovery. Saved as memory for next time.",
        S(title=STR("Short incident title, e.g. 'Checkout failing: payments bank timeout set to 50ms'"),
          summary=STR("What happened, in 2-4 sentences, for the team"),
          root_cause=STR("The cause, specific (service, commit, change)"),
          fix=STR("What fixed it"),
          evidence={"type": "array", "items": S(claim=STR("A step in the reasoning"),
                                                source=STR("Tool/data that shows it"))},
          lesson=STR("What to do differently or check first next time"))),
    "escalate": (FINISH, escalate,
        "Hand over to a human when you can't fix it safely or within budget.",
        S(reason=STR("Why you're stopping"), handover=STR("What you know and what you'd try next"))),
}


def definitions() -> list[dict]:
    return [{"name": name, "description": desc, "input_schema": schema}
            for name, (_, _, desc, schema) in TOOLS.items()]


def phase_of(name: str) -> str:
    return TOOLS[name][0]


def execute(name: str, args: dict, ctx: dict) -> str:
    if name not in TOOLS:
        raise ToolError(f"Unknown tool {name}")
    result = TOOLS[name][1](ctx, **args)
    return result if isinstance(result, str) else json.dumps(result, default=str)
