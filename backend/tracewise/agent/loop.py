"""The incident loop: plan → investigate → hypothesize → act → verify → resolve, run by Claude.

The conversation is saved after every turn, so a crashed worker's run is picked up where it
stopped. Actions are idempotent per tool call, so a resumed run never applies one twice.
"""

import json
import logging

import anthropic

from .. import config, db, emails, tracing
from . import prompt, tools

log = logging.getLogger("tracewise.agent")
MAX_NUDGES = 3
STATUS_FOR_PHASE = {"investigate": "investigating", "plan": "investigating",
                    "hypothesize": "investigating", "act": "acting", "fix": "fixing",
                    "verify": "verifying"}

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=4, timeout=600)
    return _client


# ---------- persistence ----------

def load_run(incident: dict) -> dict:
    run = db.one("SELECT * FROM agent_runs WHERE incident_id = %s", incident["id"])
    if run:
        return run
    last_deploy = db.one("SELECT coalesce(max(id), 0) AS id FROM deploys")["id"]
    last_step = db.one("SELECT coalesce(max(id), 0) AS id FROM incident_steps WHERE incident_id = %s",
                       incident["id"])["id"]
    messages = [{"role": "user", "content": prompt.kickoff(incident)}]
    return db.one(
        "INSERT INTO agent_runs (incident_id, messages, last_deploy_id, last_step_id)"
        " VALUES (%s, %s, %s, %s) RETURNING *",
        incident["id"], db.jsonb(messages), last_deploy, last_step)


def save_run(run: dict) -> None:
    db.query(
        "UPDATE agent_runs SET messages = %s, turns = %s, input_tokens = %s, output_tokens = %s,"
        " cost_usd = %s, last_deploy_id = %s, last_step_id = %s, nudges = %s WHERE incident_id = %s",
        db.jsonb(run["messages"]), run["turns"], run["input_tokens"], run["output_tokens"],
        run["cost_usd"], run["last_deploy_id"], run["last_step_id"], run["nudges"],
        run["incident_id"])


def heartbeat(incident_id: int, worker: str) -> None:
    db.query("UPDATE incidents SET lease_owner = %s,"
             " lease_until = now() + make_interval(secs => %s) WHERE id = %s",
             worker, config.LEASE_SECONDS, incident_id)


def set_status(incident_id: int, status: str) -> None:
    db.query("UPDATE incidents SET status = %s WHERE id = %s AND status NOT IN ('resolved', 'escalated')",
             status, incident_id)


# ---------- environment updates ----------

def environment_updates(run: dict) -> list[str]:
    notes = []
    for d in db.query("SELECT id, service, sha, author, message, actor FROM deploys WHERE id > %s"
                      " ORDER BY id", run["last_deploy_id"]):
        run["last_deploy_id"] = d["id"]
        if d["actor"] == "tracewise":
            continue
        notes.append(f"New deploy just landed: {d['service']} → {d['sha'][:10]} by {d['author']} "
                     f"(\"{d['message']}\", deployed by {d['actor']}).")
    for s in db.query("SELECT id, title FROM incident_steps WHERE incident_id = %s AND id > %s"
                      " AND kind = 'detector' ORDER BY id", run["incident_id"], run["last_step_id"]):
        notes.append(f"Detector: {s['title']}.")
    last = db.one("SELECT coalesce(max(id), 0) AS id FROM incident_steps WHERE incident_id = %s",
                  run["incident_id"])["id"]
    run["last_step_id"] = last
    return notes


# ---------- model ----------

def call_model(run: dict) -> list[dict]:
    response = client().beta.messages.create(
        model=config.MODEL,
        max_tokens=16000,
        system=prompt.SYSTEM,
        tools=tools.definitions(),
        messages=run["messages"],
        thinking={"type": "adaptive", "display": "summarized"},
        output_config={"effort": config.EFFORT},
        cache_control={"type": "ephemeral"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    u = response.usage
    cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    run["turns"] += 1
    run["input_tokens"] += u.input_tokens + cache_write + cache_read
    run["output_tokens"] += u.output_tokens
    run["cost_usd"] = float(run["cost_usd"]) + (
        u.input_tokens * config.PRICE_IN + cache_write * config.PRICE_IN * 1.25
        + cache_read * config.PRICE_IN * 0.05 + u.output_tokens * config.PRICE_OUT) / 1e6
    content = [b.model_dump(mode="json", exclude_none=True) for b in response.content]
    run["messages"].append({"role": "assistant", "content": content})
    run["stop_reason"] = response.stop_reason
    return content


def record_thoughts(incident_id: int, content: list[dict]) -> None:
    for block in content:
        if block["type"] == "thinking" and block.get("thinking", "").strip():
            text = block["thinking"].strip()
            db.add_step(incident_id, "thinking", text.splitlines()[0][:160], {"text": text})
        elif block["type"] == "text" and block.get("text", "").strip():
            text = block["text"].strip()
            db.add_step(incident_id, "note", text.splitlines()[0][:160], {"text": text})


# ---------- tools ----------

STEP_KIND = {"investigate": "tool", "plan": "plan", "hypothesize": "hypotheses", "act": "action",
             "fix": "fix", "verify": "verify"}


def run_tools(incident: dict, run: dict, content: list[dict], worker: str) -> str | None:
    """Execute the tool calls in the last assistant turn. Returns 'resolved'/'escalated' when done."""
    results, outcome = [], None
    for block in content:
        if block["type"] != "tool_use":
            continue
        name, args = block["name"], block.get("input") or {}
        phase = tools.phase_of(name) if name in tools.TOOLS else "investigate"
        if phase in STATUS_FOR_PHASE:
            set_status(incident["id"], STATUS_FOR_PHASE[phase])
        ctx = {"incident": incident, "tool_use_id": block["id"],
               "heartbeat": lambda: heartbeat(incident["id"], worker)}
        fn = tracing.traced("TOOL", name)(lambda a=args: tools.execute(name, a, ctx))
        try:
            output, is_error = fn(), False
        except tools.ToolError as exc:
            output, is_error = f"Error: {exc}", True
        except TypeError as exc:
            output, is_error = f"Error: bad arguments for {name}: {exc}", True
        except Exception as exc:  # a tool bug shouldn't kill the incident
            log.exception("tool %s failed", name)
            output, is_error = f"Error: {type(exc).__name__}: {exc}", True
        results.append({"type": "tool_result", "tool_use_id": block["id"], "content": output,
                        **({"is_error": True} if is_error else {})})
        try:
            parsed = json.loads(output) if not is_error else None
        except json.JSONDecodeError:
            parsed = None
        step_data = {"tool": name, "input": args, "error": output if is_error else None,
                     "result": parsed if parsed is not None else (None if is_error else output[:6000])}
        if name == "resolve_incident" and not is_error:
            finish_resolved(incident, args)
            outcome = "resolved"
        elif name == "escalate" and not is_error:
            finish_escalated(incident, args["reason"], args["handover"])
            outcome = "escalated"
        else:
            db.add_step(incident["id"], STEP_KIND.get(phase, "tool"), title_for(name, args, parsed,
                        is_error), step_data, phase=phase)
        heartbeat(incident["id"], worker)

    notes = environment_updates(run)
    if notes:
        results.append({"type": "text", "text": "[environment update] " + " ".join(notes)})
        db.add_step(incident["id"], "environment", " ".join(notes)[:160], {"notes": notes})
    run["messages"].append({"role": "user", "content": results})
    return outcome


def title_for(name: str, args: dict, parsed, is_error: bool) -> str:
    if is_error:
        return f"{name} failed"
    if name == "record_plan":
        return f"Plan: {args.get('goal', '')}"[:160]
    if name == "record_hypotheses":
        top = max(args.get("hypotheses", []), key=lambda h: h.get("confidence", 0), default={})
        return f"Top hypothesis: {top.get('cause', '')}"[:160]
    if name == "set_flag":
        return f"Set {args['name']} = {args['value']}"
    if name == "rollback_service":
        return f"Rolled back {args['service']}" + (f" to {parsed['now_running']}" if parsed else "")
    if name == "restart_service":
        return f"Restarted {args['service']}"
    if name == "request_code_fix":
        if not parsed:
            return "Code fix requested"
        return (f"{parsed['agent'].title()} agent fix {parsed['status']}"
                f" ({'tests pass' if parsed.get('tests_passed') else 'tests not passing'})")
    if name == "deploy_fix":
        return f"Deployed fix to {parsed['service']}" if parsed and parsed.get("now_running") else "Fix deploy"
    if name == "verify_recovery":
        ok = parsed and parsed.get("recovered")
        return f"{'Recovered' if ok else 'Not recovered'}: {', '.join(args['services'])}"
    target = args.get("service") or args.get("sha") or args.get("query") or args.get("symbol") or ""
    return f"{name} {target}".strip()[:160]


# ---------- finishing ----------

def finish_resolved(incident: dict, a: dict) -> None:
    db.query("UPDATE incidents SET status = 'resolved', resolved_at = now(), title = %s, summary = %s,"
             " root_cause = %s, fix = %s, lease_owner = NULL WHERE id = %s",
             a["title"], a["summary"], a["root_cause"], a["fix"], incident["id"])
    symptoms = f"{incident['title']}. {a['summary']}"
    db.query("INSERT INTO memories (incident_id, services, symptoms, root_cause, fix, outcome)"
             " VALUES (%s, %s, %s, %s, %s, %s)", incident["id"], incident["services"], symptoms,
             a["root_cause"], a["fix"], f"Resolved and verified. Lesson: {a['lesson']}")
    db.add_step(incident["id"], "resolve", a["title"], a, phase="finish")
    db.query("UPDATE agent_runs SET finished_at = now() WHERE incident_id = %s", incident["id"])
    notify_incident(incident["id"], "resolved")


def finish_escalated(incident: dict, reason: str, handover: str) -> None:
    db.query("UPDATE incidents SET status = 'escalated', summary = %s, lease_owner = NULL"
             " WHERE id = %s", handover, incident["id"])
    db.add_step(incident["id"], "escalate", reason[:160], {"reason": reason, "handover": handover},
                phase="finish")
    db.query("UPDATE agent_runs SET finished_at = now() WHERE incident_id = %s", incident["id"])
    notify_incident(incident["id"], "escalated", reason, handover)


def notify_incident(incident_id: int, outcome: str, reason: str = "", handover: str = "") -> None:
    """Email workspace members whose notification setting covers this outcome."""
    try:
        inc = db.one("SELECT i.*, r.cost_usd FROM incidents i LEFT JOIN agent_runs r ON r.incident_id = i.id"
                     " WHERE i.id = %s", incident_id)
        wanted = ("all",) if outcome == "resolved" else ("all", "escalations")
        people = db.query("SELECT DISTINCT u.email FROM users u JOIN workspace_members m ON m.user_id = u.id"
                          " WHERE u.notify_incidents = ANY(%s)", list(wanted))
        for p in people:
            if outcome == "resolved":
                took = (inc["resolved_at"] - inc["opened_at"]).total_seconds()
                emails.incident_resolved(p["email"], inc, f"{int(took // 60)}m {int(took % 60):02d}s",
                                         f"${float(inc['cost_usd'] or 0):.2f}")
            else:
                emails.incident_escalated(p["email"], inc, reason, handover)
    except Exception:
        log.exception("incident %s notification failed", incident_id)


# ---------- main loop ----------

def run_incident(incident_id: int, worker: str) -> None:
    incident = db.one("SELECT * FROM incidents WHERE id = %s", incident_id)
    run = load_run(incident)
    attempt = 1 + db.one("SELECT count(*) AS n FROM incident_steps WHERE incident_id = %s"
                         " AND kind = 'resume'", incident_id)["n"]
    if run["turns"] > 0:
        db.add_step(incident_id, "resume", f"Resumed after interruption (turn {run['turns']})")
    else:
        set_status(incident_id, "investigating")

    with tracing.incident_trace(incident, attempt):
        try:
            _loop(incident, run, worker)
        finally:
            save_run(run)
            tracing.flush()


def _loop(incident: dict, run: dict, worker: str) -> None:
    while True:
        heartbeat(incident["id"], worker)
        last = run["messages"][-1]
        if last["role"] == "assistant":
            content = last["content"]
            if any(b["type"] == "tool_use" for b in content):
                outcome = run_tools(incident, run, content, worker)
                save_run(run)
                if outcome:
                    return
                continue
            # The model ended its turn without finishing.
            if run.get("stop_reason") == "refusal" or run["nudges"] >= MAX_NUDGES:
                finish_escalated(incident, "The agent stopped without a resolution.",
                                 "See the timeline for what was tried.")
                return
            run["nudges"] += 1
            notes = environment_updates(run)
            run["messages"].append({"role": "user", "content": (
                "You ended your turn without resolving or escalating. Continue working: take the "
                "next step, or call resolve_incident / escalate." +
                (" [environment update] " + " ".join(notes) if notes else ""))})
            save_run(run)
            continue

        if run["turns"] >= config.MAX_TURNS or float(run["cost_usd"]) >= config.MAX_COST_USD:
            finish_escalated(incident, f"Budget reached ({run['turns']} turns, "
                             f"${float(run['cost_usd']):.2f}).", "See the timeline for what was tried.")
            return
        try:
            content = call_model(run)
        except anthropic.APIStatusError as exc:
            db.add_step(incident["id"], "error", f"Model call failed ({exc.status_code})",
                        {"error": str(exc)[:2000]})
            raise
        save_run(run)
        record_thoughts(incident["id"], content)
