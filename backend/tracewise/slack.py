"""The Tracewise Slack app.

- Install with "Add to Slack" (OAuth v2). The bot token is stored encrypted, per Tracewise workspace.
- Each project routes its incidents to a channel. An incident becomes one thread: the root message
  shows live status (open → acting → resolved/escalated) and the agent's actions, fixes and outcome
  are posted as replies; the outcome is also broadcast to the channel.
- Buttons: Acknowledge (recorded on the incident's timeline) and Open timeline.
- Slash command: /tracewise status | incidents | help.
- Every request from Slack is checked against the app's signing secret.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets as pysecrets
import threading
import time
from urllib.parse import parse_qs, urlencode, quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import db, secrets
from .emails import WEB_URL

log = logging.getLogger("tracewise.slack")
router = APIRouter(prefix="/v1/slack")

CLIENT_ID = os.environ.get("SLACK_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SLACK_CLIENT_SECRET", "")
SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
API = os.environ.get("SLACK_API_BASE", "https://slack.com/api").rstrip("/")
AUTHORIZE = os.environ.get("SLACK_AUTHORIZE_URL", "https://slack.com/oauth/v2/authorize")
PUBLIC_URL = os.environ.get("TW_PUBLIC_URL", "http://localhost:19100").rstrip("/")
# users:read.email lets an Approve click be tied to a Tracewise member by their Slack email.
SCOPES = "chat:write,chat:write.public,channels:read,groups:read,commands,users:read,users:read.email"
EVENTS = ("opened", "approval", "action", "fix", "resolved", "escalated")
_STATE_KEY = (os.environ.get("TW_SECRET_KEY") or "tracewise-dev").encode()


def configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET and SIGNING_SECRET)


def manifest() -> dict:
    """Everything Slack needs to create the app, pre-filled for this install."""
    return {
        "display_information": {"name": "Tracewise", "description": "The on-call agent that fixes production and shows its work.",
                                "background_color": "#111111"},
        "features": {
            "bot_user": {"display_name": "Tracewise", "always_online": True},
            "slash_commands": [{"command": "/tracewise", "url": f"{PUBLIC_URL}/v1/slack/commands",
                                "description": "Incidents and service health", "usage_hint": "status | incidents | help",
                                "should_escape": False}],
        },
        "oauth_config": {"redirect_urls": [f"{PUBLIC_URL}/v1/slack/oauth/callback"],
                         "scopes": {"bot": SCOPES.split(",")}},
        "settings": {"interactivity": {"is_enabled": True, "request_url": f"{PUBLIC_URL}/v1/slack/interactions"},
                     "org_deploy_enabled": False, "socket_mode_enabled": False, "token_rotation_enabled": False},
    }


def manifest_url() -> str:
    return "https://api.slack.com/apps?new_app=1&manifest_json=" + quote(json.dumps(manifest()))


# ---------------------------------------------------------------- Slack Web API

class SlackError(Exception):
    pass


def call(token: str, method: str, **payload) -> dict:
    r = httpx.post(f"{API}/{method}", json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    data = r.json()
    if not data.get("ok"):
        raise SlackError(data.get("error", "unknown_error"))
    return data


def token_for_workspace(workspace_id: int) -> tuple[dict, str] | None:
    inst = db.one("SELECT * FROM slack_installations WHERE workspace_id = %s", workspace_id)
    return (inst, secrets.decrypt(bytes(inst["bot_token"]))) if inst else None


# ---------------------------------------------------------------- signatures and install state

def verify(request: Request, body: bytes) -> None:
    ts = request.headers.get("x-slack-request-timestamp", "0")
    sig = request.headers.get("x-slack-signature", "")
    if not SIGNING_SECRET or not ts.isdigit() or abs(time.time() - int(ts)) > 300:
        raise HTTPException(401, "stale or unsigned request")
    expected = "v0=" + hmac.new(SIGNING_SECRET.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(401, "bad signature")


def _sign_state(data: dict) -> str:
    raw = json.dumps({**data, "n": pysecrets.token_hex(8), "t": int(time.time())}, separators=(",", ":"))
    mac = hmac.new(_STATE_KEY, raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{raw.encode().hex()}.{mac}"


def _read_state(state: str) -> dict:
    try:
        raw_hex, mac = state.split(".")
        raw = bytes.fromhex(raw_hex).decode()
    except ValueError:
        raise HTTPException(400, "bad state")
    if not hmac.compare_digest(mac, hmac.new(_STATE_KEY, raw.encode(), hashlib.sha256).hexdigest()[:32]):
        raise HTTPException(400, "bad state")
    data = json.loads(raw)
    if time.time() - data["t"] > 900:
        raise HTTPException(400, "This install link expired. Start again from Tracewise.")
    return data


# ---------------------------------------------------------------- settings API (signed-in admins)

def _ctx(request: Request, admin: bool = False) -> dict:
    from .auth import rank, require
    ctx = require(request)
    if not ctx.get("workspace"):
        raise HTTPException(403, "Create or join a workspace first.")
    if admin and rank(ctx["role"]) < rank("admin"):
        raise HTTPException(403, "Only admins can manage the Slack app.")
    return ctx


@router.get("/status")
def status(request: Request):
    ctx = _ctx(request)
    inst = db.one("SELECT s.team_id, s.team_name, s.created_at, u.email AS installed_by FROM slack_installations s"
                  " LEFT JOIN users u ON u.id = s.installed_by WHERE s.workspace_id = %s", ctx["workspace"]["id"])
    routes = db.query("SELECT r.project_id, p.name AS project, p.slug, r.channel_id, r.channel_name, r.events"
                      " FROM projects p LEFT JOIN slack_routes r ON r.project_id = p.id"
                      " WHERE p.workspace_id = %s ORDER BY p.created_at", ctx["workspace"]["id"])
    for r in routes:
        r["project_id"] = r["project_id"] or db.one("SELECT id FROM projects WHERE slug = %s AND workspace_id = %s",
                                                    r["slug"], ctx["workspace"]["id"])["id"]
    return {"configured": configured(), "installed": inst, "routes": routes, "events": EVENTS,
            "manifest_url": manifest_url(), "manifest": manifest()}


@router.get("/install-url")
def install_url(request: Request):
    ctx = _ctx(request, admin=True)
    if not configured():
        raise HTTPException(503, "The Slack app isn't configured on this server yet.")
    state = _sign_state({"w": ctx["workspace"]["id"], "u": ctx["user"]["id"]})
    return {"url": f"{AUTHORIZE}?" + urlencode({"client_id": CLIENT_ID, "scope": SCOPES, "state": state,
                                                 "redirect_uri": f"{PUBLIC_URL}/v1/slack/oauth/callback"})}


@router.get("/oauth/callback")
def oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Public: Slack sends the installer back here; the signed state says which workspace."""
    back = f"{WEB_URL}/settings/integrations"
    if error:
        return RedirectResponse(f"{back}?slack=cancelled")
    s = _read_state(state)
    r = httpx.post(f"{API}/oauth.v2.access", data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": code,
                                                   "redirect_uri": f"{PUBLIC_URL}/v1/slack/oauth/callback"}, timeout=15).json()
    if not r.get("ok"):
        return RedirectResponse(f"{back}?slack=error&reason={r.get('error', 'unknown')}")
    db.query("INSERT INTO slack_installations (workspace_id, team_id, team_name, bot_user_id, bot_token, scope, installed_by)"
             " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (workspace_id) DO UPDATE SET team_id = EXCLUDED.team_id,"
             " team_name = EXCLUDED.team_name, bot_user_id = EXCLUDED.bot_user_id, bot_token = EXCLUDED.bot_token,"
             " scope = EXCLUDED.scope, installed_by = EXCLUDED.installed_by, created_at = now()",
             s["w"], r["team"]["id"], r["team"].get("name"), r.get("bot_user_id"),
             secrets.encrypt(r["access_token"]), r.get("scope"), s["u"])
    return RedirectResponse(f"{back}?slack=connected")


@router.get("/channels")
def channels(request: Request):
    ctx = _ctx(request, admin=True)
    found = token_for_workspace(ctx["workspace"]["id"])
    if not found:
        raise HTTPException(404, "Slack isn't connected.")
    out, cursor = [], None
    for _ in range(10):
        data = call(found[1], "conversations.list", types="public_channel,private_channel", exclude_archived=True,
                    limit=200, **({"cursor": cursor} if cursor else {}))
        out += [{"id": c["id"], "name": c["name"], "private": c.get("is_private", False), "member": c.get("is_member", False)}
                for c in data.get("channels", [])]
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return sorted(out, key=lambda c: c["name"])


@router.put("/routes/{project_id}")
def set_route(project_id: int, body: dict, request: Request):
    ctx = _ctx(request, admin=True)
    if not db.one("SELECT 1 FROM projects WHERE id = %s AND workspace_id = %s", project_id, ctx["workspace"]["id"]):
        raise HTTPException(404, "Project not found.")
    if not body.get("channel_id"):
        db.query("DELETE FROM slack_routes WHERE project_id = %s", project_id)
        return {"removed": True}
    events = [e for e in body.get("events") or EVENTS if e in EVENTS]
    return db.one("INSERT INTO slack_routes (project_id, channel_id, channel_name, events) VALUES (%s, %s, %s, %s)"
                  " ON CONFLICT (project_id) DO UPDATE SET channel_id = EXCLUDED.channel_id,"
                  " channel_name = EXCLUDED.channel_name, events = EXCLUDED.events, updated_at = now() RETURNING *",
                  project_id, body["channel_id"], body.get("channel_name"), events)


@router.post("/test/{project_id}")
def send_test(project_id: int, request: Request):
    ctx = _ctx(request, admin=True)
    route = db.one("SELECT r.*, p.name FROM slack_routes r JOIN projects p ON p.id = r.project_id"
                   " WHERE r.project_id = %s AND p.workspace_id = %s", project_id, ctx["workspace"]["id"])
    found = token_for_workspace(ctx["workspace"]["id"])
    if not route or not found:
        raise HTTPException(400, "Connect Slack and choose a channel first.")
    try:
        call(found[1], "chat.postMessage", channel=route["channel_id"], text=f"Tracewise is connected for {route['name']}.",
             blocks=[{"type": "section", "text": {"type": "mrkdwn", "text":
                      f":white_check_mark: *Tracewise is connected.* Incidents in *{route['name']}* will be posted here as threads."}}])
    except SlackError as exc:
        raise HTTPException(400, f"Slack said: {exc}" + (" (invite @Tracewise to the private channel)" if str(exc) == "not_in_channel" else ""))
    return {"sent": True}


@router.delete("/installation")
def uninstall(request: Request):
    ctx = _ctx(request, admin=True)
    found = token_for_workspace(ctx["workspace"]["id"])
    if found:
        try:
            call(found[1], "apps.uninstall", client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
        except Exception:
            pass
    db.query("DELETE FROM slack_installations WHERE workspace_id = %s", ctx["workspace"]["id"])
    return {"removed": True}


# ---------------------------------------------------------------- messages

STATUS = {"open": ("Open", ":red_circle:"), "investigating": ("Investigating", ":large_blue_circle:"),
          "acting": ("Acting", ":large_orange_circle:"), "fixing": ("Writing a fix", ":large_orange_circle:"),
          "verifying": ("Verifying", ":large_blue_circle:"), "resolved": ("Resolved", ":large_green_circle:"),
          "escalated": ("Needs a human", ":warning:")}


def incident_blocks(inc: dict, project: str) -> list[dict]:
    label, dot = STATUS.get(inc["status"], (inc["status"], ":white_circle:"))
    url = f"{WEB_URL}/incidents/{inc['id']}"
    signals = []
    for s in (inc.get("signals") or [])[:6]:
        line = f"`{s['service']}` {s['status']}"
        if s.get("requests"):
            line += f" · errors {s['error_rate']:.0%} (normally {(s.get('baseline_error_rate') or 0):.0%})"
        for a in (s.get("alerts") or [])[:1]:
            line += f" · {a['source']}: {a['title']}"
        signals.append(line)
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Incident #{inc['id']}: {inc['title']}"[:150]}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{dot} *{label}* · {project} · {inc['severity']} severity"
                                          + (f" · acknowledged by {inc['acknowledged_by']}" if inc.get("acknowledged_by") else "")}]},
    ]
    if inc["status"] in ("resolved", "escalated") and (inc.get("root_cause") or inc.get("summary")):
        text = f"*Root cause:* {inc['root_cause']}\n*Fix:* {inc.get('fix') or '—'}" if inc["status"] == "resolved" \
            else (inc.get("summary") or "")[:1500]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}})
    elif signals:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(signals)}})
    actions = [{"type": "button", "text": {"type": "plain_text", "text": "Open timeline"}, "url": url, "action_id": "open"}]
    if not inc.get("acknowledged_by") and inc["status"] not in ("resolved",):
        actions.insert(0, {"type": "button", "text": {"type": "plain_text", "text": "Acknowledge"}, "style": "primary",
                           "action_id": "ack", "value": str(inc["id"])})
    blocks.append({"type": "actions", "elements": actions})
    return blocks


def step_text(step: dict) -> str | None:
    d = step.get("data") or {}
    kind = step["kind"]
    if kind == "action":
        return f":zap: *{step['title']}*" + (f"\n>{d['input'].get('reason')}" if (d.get("input") or {}).get("reason") else "")
    if kind == "fix":
        r = d.get("result") or {}
        bits = [f":wrench: *{step['title']}*"]
        if r.get("commit"):
            bits.append(f"commit `{r['commit']}` on `{r.get('branch')}`, tests {'passed' if r.get('tests_passed') else 'failed'}")
        return "\n".join(bits)
    if kind == "verify":
        return f":white_check_mark: {step['title']}" if "Recovered" in step["title"] else f":hourglass: {step['title']}"
    if kind == "resolve":
        return (f":large_green_circle: *Resolved:* {d.get('title') or step['title']}\n*Root cause:* {d.get('root_cause', '—')}\n"
                f"*Fix:* {d.get('fix', '—')}")
    if kind == "escalate":
        return f":warning: *The agent needs a human:* {d.get('reason', step['title'])}\n\n{(d.get('handover') or '')[:2500]}"
    if kind == "detector" and step["title"].startswith("Also affected"):
        return f":rotating_light: {step['title']}"
    return None


EVENT_OF = {"action": "action", "fix": "fix", "verify": "action", "resolve": "resolved", "escalate": "escalated",
            "detector": "opened", "approval": "approval", "approval_decision": "approval"}


def approval_blocks(a: dict) -> list[dict]:
    from .approvals import describe
    p = a.get("params") or {}
    head = {"pending": ":raised_hand: *Approval needed*", "approved": ":white_check_mark: *Approved*",
            "rejected": ":no_entry: *Rejected*", "expired": ":hourglass: *Expired*"}[a["status"]]
    text = f"{head}: {describe(a)}"
    if p.get("reason"):
        text += f"\n>{p['reason'][:1500]}"
    if a["status"] != "pending":
        text += f"\n_{(a.get('decided_by') or 'Nobody') + (' via ' + a['decided_via'] if a.get('decided_via') not in (None, 'system') else '')}"
        text += (f": {a['note']}" if a.get("note") else "") + "_"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]
    if a["status"] == "pending":
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary", "action_id": "approve",
             "value": str(a["id"]), "confirm": {"title": {"type": "plain_text", "text": "Approve this action?"},
                                                "text": {"type": "plain_text", "text": describe(a)[:290]},
                                                "confirm": {"type": "plain_text", "text": "Approve"}, "deny": {"type": "plain_text", "text": "Cancel"}}},
            {"type": "button", "text": {"type": "plain_text", "text": "Reject"}, "style": "danger", "action_id": "reject", "value": str(a["id"])},
            {"type": "button", "text": {"type": "plain_text", "text": "Open timeline"}, "url": f"{WEB_URL}/incidents/{a['incident_id']}", "action_id": "open"},
        ]})
    return blocks


def refresh_approval(approval_id: int) -> None:
    a = db.one("SELECT * FROM approvals WHERE id = %s", approval_id)
    inc = db.one("SELECT * FROM incidents WHERE id = %s", a["incident_id"]) if a else None
    target = _project_route(inc) if inc else None
    if a and a["slack_ts"] and target:
        call(target[1], "chat.update", channel=a["slack_channel"], ts=a["slack_ts"], text="Approval: " + a["kind"],
             blocks=approval_blocks(a))


def _project_route(incident: dict) -> tuple[dict, str, str] | None:
    route = db.one("SELECT r.*, p.workspace_id, p.name AS project FROM slack_routes r JOIN projects p ON p.id = r.project_id"
                   " WHERE r.project_id = %s", incident["project_id"])
    if not route:
        return None
    found = token_for_workspace(route["workspace_id"])
    return (route, found[1], route["project"]) if found else None


def refresh_root(incident_id: int) -> None:
    """Re-render the thread's root message from the incident's current state."""
    inc = db.one("SELECT * FROM incidents WHERE id = %s", incident_id)
    thread = db.one("SELECT * FROM slack_threads WHERE incident_id = %s", incident_id)
    target = _project_route(inc) if inc else None
    if thread and target:
        call(target[1], "chat.update", channel=thread["channel_id"], ts=thread["ts"],
             text=f"Incident #{inc['id']}: {inc['title']}", blocks=incident_blocks(inc, target[2]))


def post_step(step: dict) -> None:
    inc = db.one("SELECT * FROM incidents WHERE id = %s", step["incident_id"])
    target = _project_route(inc) if inc else None
    if not target:
        return
    route, token, project = target
    event = EVENT_OF.get(step["kind"])
    thread = db.one("SELECT * FROM slack_threads WHERE incident_id = %s", inc["id"])
    if not thread:
        if "opened" not in route["events"] and event not in route["events"]:
            return
        r = call(token, "chat.postMessage", channel=route["channel_id"], text=f"Incident #{inc['id']}: {inc['title']}",
                 blocks=incident_blocks(inc, project), unfurl_links=False)
        db.query("INSERT INTO slack_threads (incident_id, channel_id, ts) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                 inc["id"], r["channel"], r["ts"])
        thread = {"channel_id": r["channel"], "ts": r["ts"]}
        if step["kind"] == "detector" and not step["title"].startswith("Also affected"):
            return  # the root message is the "opened" post
    if step["kind"] == "approval":
        a = db.one("SELECT * FROM approvals WHERE id = %s", (step.get("data") or {}).get("approval_id"))
        if a and "approval" in route["events"]:
            r = call(token, "chat.postMessage", channel=thread["channel_id"], thread_ts=thread["ts"], reply_broadcast=True,
                     text="Approval needed", blocks=approval_blocks(a), unfurl_links=False)
            db.query("UPDATE approvals SET slack_channel = %s, slack_ts = %s WHERE id = %s", r["channel"], r["ts"], a["id"])
        return
    if step["kind"] == "approval_decision":
        refresh_approval((step.get("data") or {}).get("approval_id"))
        return
    text = step_text(step)
    if text and event in route["events"]:
        call(token, "chat.postMessage", channel=thread["channel_id"], thread_ts=thread["ts"], text=text[:3000],
             reply_broadcast=step["kind"] in ("resolve", "escalate"), unfurl_links=False)
    call(token, "chat.update", channel=thread["channel_id"], ts=thread["ts"], text=f"Incident #{inc['id']}: {inc['title']}",
         blocks=incident_blocks(inc, project))


def notifier_loop() -> None:
    """Runs in the worker: posts new timeline steps for incidents in projects routed to Slack."""
    start = db.one("SELECT step_id FROM slack_cursor WHERE id = 1")
    if not start:  # first run: don't replay history into Slack
        db.query("INSERT INTO slack_cursor (id, step_id) SELECT 1, coalesce(max(id), 0) FROM incident_steps"
                 " ON CONFLICT (id) DO NOTHING")
    while True:
        try:
            cursor = db.one("SELECT step_id FROM slack_cursor WHERE id = 1")["step_id"]
            steps = db.query(
                "SELECT s.* FROM incident_steps s JOIN incidents i ON i.id = s.incident_id"
                " JOIN slack_routes r ON r.project_id = i.project_id"
                " WHERE s.id > %s AND s.kind IN ('detector', 'action', 'fix', 'verify', 'resolve', 'escalate',"
                " 'approval', 'approval_decision')"
                " AND NOT EXISTS (SELECT 1 FROM slack_posts p WHERE p.step_id = s.id) ORDER BY s.id LIMIT 50", cursor)
            for step in steps:
                try:
                    post_step(step)
                except SlackError as exc:
                    log.warning("slack post for step %s failed: %s", step["id"], exc)
                db.query("INSERT INTO slack_posts (step_id) VALUES (%s) ON CONFLICT DO NOTHING", step["id"])
            newest = db.one("SELECT coalesce(max(id), 0) AS id FROM incident_steps")["id"]
            if not steps:
                db.query("UPDATE slack_cursor SET step_id = %s WHERE id = 1", newest)
        except Exception:
            log.exception("slack notifier")
        time.sleep(2)


def start_notifier() -> None:
    threading.Thread(target=notifier_loop, daemon=True, name="slack").start()


# ---------------------------------------------------------------- requests from Slack

def _installation_for_team(team_id: str) -> dict | None:
    return db.one("SELECT * FROM slack_installations WHERE team_id = %s ORDER BY created_at DESC LIMIT 1", team_id)


@router.post("/interactions")
async def interactions(request: Request):
    body = await request.body()
    verify(request, body)
    payload = json.loads(parse_qs(body.decode())["payload"][0])
    inst = _installation_for_team(payload.get("team", {}).get("id", ""))
    if not inst:
        return JSONResponse({"text": "This Slack workspace isn't connected to Tracewise."})
    for action in payload.get("actions", []):
        if action.get("action_id") in ("approve", "reject"):
            reply = _decide_from_slack(inst, payload, int(action["value"]), action["action_id"])
            if reply:
                return JSONResponse({"response_type": "ephemeral", "replace_original": False, "text": reply})
            continue
        if action.get("action_id") != "ack":
            continue
        inc = db.one("SELECT i.* FROM incidents i JOIN projects p ON p.id = i.project_id"
                     " WHERE i.id = %s AND p.workspace_id = %s", int(action["value"]), inst["workspace_id"])
        if not inc:
            continue
        who = payload.get("user", {}).get("name") or payload.get("user", {}).get("username") or "someone"
        if not inc["acknowledged_by"]:
            db.query("UPDATE incidents SET acknowledged_by = %s, acknowledged_at = now() WHERE id = %s", f"@{who}", inc["id"])
            db.add_step(inc["id"], "note", f"Acknowledged by @{who} in Slack", {"text": f"Acknowledged by @{who} in Slack"})
        threading.Thread(target=lambda i=inc["id"]: _safe(refresh_root, i), daemon=True).start()
    return Response(status_code=200)


def _decide_from_slack(inst: dict, payload: dict, approval_id: int, action_id: str) -> str | None:
    """Only a Tracewise member (member or above) of this workspace may approve, matched by Slack email."""
    from .approvals import decide, member_by_email
    a = db.one("SELECT a.* FROM approvals a JOIN projects p ON p.id = a.project_id WHERE a.id = %s AND p.workspace_id = %s",
               approval_id, inst["workspace_id"])
    if not a:
        return "That approval isn't in this workspace."
    if a["status"] != "pending":
        return f"Already {a['status']}" + (f" by {a['decided_by']}." if a["decided_by"] else ".")
    slack_user = payload.get("user", {}).get("id")
    try:
        info = call(secrets.decrypt(bytes(inst["bot_token"])), "users.info", user=slack_user)
        email = (info.get("user") or {}).get("profile", {}).get("email")
    except SlackError:
        email = None
    person = member_by_email(inst["workspace_id"], email)
    if not person:
        return (f"Only Tracewise members can approve production actions. Your Slack email ({email or 'hidden'}) "
                "isn't a member of this workspace with permission to act.")
    decide(approval_id, "approved" if action_id == "approve" else "rejected", person.get("name") or person["email"], "slack")
    threading.Thread(target=lambda: _safe(refresh_approval, approval_id), daemon=True).start()
    return None


def _safe(fn, *args):
    try:
        fn(*args)
    except Exception as exc:
        log.warning("slack: %s", exc)


@router.post("/commands")
async def commands(request: Request):
    body = await request.body()
    verify(request, body)
    form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
    inst = _installation_for_team(form.get("team_id", ""))
    if not inst:
        return JSONResponse({"response_type": "ephemeral", "text": "This Slack workspace isn't connected to Tracewise yet."})
    words = (form.get("text") or "").split()
    sub = words[0].lower() if words else "status"
    projects = db.query("SELECT * FROM projects WHERE workspace_id = %s ORDER BY created_at", inst["workspace_id"])
    if len(words) > 1:
        projects = [p for p in projects if p["slug"] == words[1] or p["name"].lower() == words[1].lower()] or projects
    if sub == "help":
        return JSONResponse({"response_type": "ephemeral", "text": "*Tracewise*\n`/tracewise status [project]`: service health and open incidents\n"
                             "`/tracewise incidents [project]`: the last 10 incidents\n`/tracewise help`"})
    blocks = []
    for p in projects[:5]:
        if sub == "incidents":
            rows = db.query("SELECT id, title, status FROM incidents WHERE project_id = %s ORDER BY id DESC LIMIT 10", p["id"])
            lines = [f"{STATUS.get(r['status'], ('', ':white_circle:'))[1]} <{WEB_URL}/incidents/{r['id']}|#{r['id']}> {r['title']}"
                     for r in rows] or ["No incidents yet."]
        else:
            from .health import snapshot
            snap = snapshot(p["id"])
            bad = [s for s in snap if s["status"] != "healthy"]
            open_rows = db.query("SELECT id, title FROM incidents WHERE project_id = %s AND status IN"
                                 " ('open','investigating','acting','fixing','verifying') ORDER BY id DESC", p["id"])
            lines = [f":large_green_circle: {len(snap)} services healthy" if not bad else
                     f":red_circle: {len(bad)} of {len(snap)} unhealthy: " + ", ".join(f"`{s['service']}` {s['status']}" for s in bad[:8])]
            lines += [f":rotating_light: <{WEB_URL}/incidents/{r['id']}|#{r['id']}> {r['title']} (agent working)" for r in open_rows]
        blocks += [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{p['name']}*\n" + "\n".join(lines)[:2900]}}]
    return JSONResponse({"response_type": "ephemeral", "blocks": blocks or [{"type": "section", "text": {"type": "mrkdwn", "text": "No projects yet."}}]})
