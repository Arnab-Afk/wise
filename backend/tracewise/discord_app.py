"""The Tracewise Discord app.

- Install with "Add to Discord" (bot + /tracewise command). One Discord server per Tracewise workspace.
- Each project routes incidents to a channel: one message per incident whose embed shows live status,
  with a thread under it for the agent's actions, fixes and outcome.
- Buttons: Acknowledge (recorded on the timeline) and Open timeline. Approval requests link to the
  Tracewise console: Discord can't tell us who someone is without linking accounts, so production
  actions are approved where identity is checked.
- /tracewise view:status|incidents [project].
- Every interaction from Discord is verified with the app's Ed25519 public key.
"""

import json
import logging
import os
import threading
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import db
from .emails import WEB_URL
from .slack import STATUS, _ctx, _read_state, _safe, _sign_state

log = logging.getLogger("tracewise.discord")
router = APIRouter(prefix="/v1/discord")

APP_ID = os.environ.get("DISCORD_APP_ID", "")
PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
API = os.environ.get("DISCORD_API_BASE", "https://discord.com/api/v10").rstrip("/")
AUTHORIZE = os.environ.get("DISCORD_AUTHORIZE_URL", "https://discord.com/oauth2/authorize")
PUBLIC_URL = os.environ.get("TW_PUBLIC_URL", "http://localhost:19100").rstrip("/")
EVENTS = ("opened", "approval", "action", "fix", "resolved", "escalated")
# View channels, send messages, embed links, read history, create public threads, send in threads.
PERMISSIONS = 1024 | 2048 | 16384 | 65536 | (1 << 35) | (1 << 38)
COLOR = {"open": 0xE5484D, "investigating": 0x3E7BFA, "acting": 0xF5A524, "fixing": 0xF5A524, "verifying": 0x3E7BFA,
         "resolved": 0x30A46C, "escalated": 0xF5A524}


def configured() -> bool:
    return bool(APP_ID and PUBLIC_KEY and BOT_TOKEN and CLIENT_SECRET)


class DiscordError(Exception):
    pass


def call(method: str, path: str, body: dict | None = None) -> dict | list:
    r = httpx.request(method, f"{API}{path}", json=body, timeout=15,
                      headers={"Authorization": f"Bot {BOT_TOKEN}", "User-Agent": "Tracewise (https://tracewise, 1.0)"})
    if r.status_code >= 400:
        raise DiscordError(f"{r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


# ---------------------------------------------------------------- settings API

@router.get("/status")
def status(request: Request):
    ctx = _ctx(request)
    inst = db.one("SELECT d.guild_id, d.guild_name, d.created_at, u.email AS installed_by FROM discord_installations d"
                  " LEFT JOIN users u ON u.id = d.installed_by WHERE d.workspace_id = %s", ctx["workspace"]["id"])
    routes = db.query("SELECT p.id AS project_id, p.name AS project, p.slug, r.channel_id, r.channel_name, r.events"
                      " FROM projects p LEFT JOIN discord_routes r ON r.project_id = p.id WHERE p.workspace_id = %s"
                      " ORDER BY p.created_at", ctx["workspace"]["id"])
    return {"configured": configured(), "installed": inst, "routes": routes, "events": EVENTS,
            "setup": {"interactions_url": f"{PUBLIC_URL}/v1/discord/interactions",
                      "redirect_url": f"{PUBLIC_URL}/v1/discord/oauth/callback"}}


@router.get("/install-url")
def install_url(request: Request):
    ctx = _ctx(request, admin=True)
    if not configured():
        raise HTTPException(503, "The Discord app isn't configured on this server yet.")
    state = _sign_state({"w": ctx["workspace"]["id"], "u": ctx["user"]["id"]})
    return {"url": f"{AUTHORIZE}?" + urlencode({
        "client_id": APP_ID, "scope": "bot applications.commands", "permissions": PERMISSIONS, "response_type": "code",
        "redirect_uri": f"{PUBLIC_URL}/v1/discord/oauth/callback", "state": state, "integration_type": 0})}


def register_command() -> None:
    call("PUT", f"/applications/{APP_ID}/commands", [{
        "name": "tracewise", "description": "Incidents and service health", "type": 1,
        "options": [{"type": 3, "name": "view", "description": "What to show", "required": False,
                     "choices": [{"name": "status", "value": "status"}, {"name": "incidents", "value": "incidents"}]},
                    {"type": 3, "name": "project", "description": "Project slug", "required": False}]}])


@router.get("/oauth/callback")
def oauth_callback(code: str = "", state: str = "", error: str = ""):
    back = f"{WEB_URL}/settings/integrations"
    if error:
        return RedirectResponse(f"{back}?discord=cancelled")
    s = _read_state(state)
    r = httpx.post(f"{API}/oauth2/token", timeout=15, data={
        "client_id": APP_ID, "client_secret": CLIENT_SECRET, "grant_type": "authorization_code", "code": code,
        "redirect_uri": f"{PUBLIC_URL}/v1/discord/oauth/callback"})
    guild = (r.json() or {}).get("guild") if r.status_code == 200 else None
    if not guild:
        return RedirectResponse(f"{back}?discord=error")
    db.query("INSERT INTO discord_installations (workspace_id, guild_id, guild_name, installed_by) VALUES (%s, %s, %s, %s)"
             " ON CONFLICT (workspace_id) DO UPDATE SET guild_id = EXCLUDED.guild_id, guild_name = EXCLUDED.guild_name,"
             " installed_by = EXCLUDED.installed_by, created_at = now()", s["w"], guild["id"], guild.get("name"), s["u"])
    threading.Thread(target=lambda: _safe(register_command), daemon=True).start()
    return RedirectResponse(f"{back}?discord=connected")


def _install(request: Request) -> tuple[dict, dict]:
    ctx = _ctx(request, admin=True)
    inst = db.one("SELECT * FROM discord_installations WHERE workspace_id = %s", ctx["workspace"]["id"])
    if not inst:
        raise HTTPException(404, "Discord isn't connected.")
    return ctx, inst


@router.get("/channels")
def channels(request: Request):
    _, inst = _install(request)
    rows = call("GET", f"/guilds/{inst['guild_id']}/channels")
    return sorted([{"id": c["id"], "name": c["name"]} for c in rows if c.get("type") in (0, 5)], key=lambda c: c["name"])


@router.put("/routes/{project_id}")
def set_route(project_id: int, body: dict, request: Request):
    ctx, _ = _install(request)
    if not db.one("SELECT 1 FROM projects WHERE id = %s AND workspace_id = %s", project_id, ctx["workspace"]["id"]):
        raise HTTPException(404, "Project not found.")
    if not body.get("channel_id"):
        db.query("DELETE FROM discord_routes WHERE project_id = %s", project_id)
        return {"removed": True}
    events = [e for e in body.get("events") or EVENTS if e in EVENTS]
    return db.one("INSERT INTO discord_routes (project_id, channel_id, channel_name, events) VALUES (%s, %s, %s, %s)"
                  " ON CONFLICT (project_id) DO UPDATE SET channel_id = EXCLUDED.channel_id, channel_name = EXCLUDED.channel_name,"
                  " events = EXCLUDED.events, updated_at = now() RETURNING *", project_id, body["channel_id"],
                  body.get("channel_name"), events)


@router.post("/test/{project_id}")
def send_test(project_id: int, request: Request):
    ctx, _ = _install(request)
    route = db.one("SELECT r.*, p.name FROM discord_routes r JOIN projects p ON p.id = r.project_id"
                   " WHERE r.project_id = %s AND p.workspace_id = %s", project_id, ctx["workspace"]["id"])
    if not route:
        raise HTTPException(400, "Choose a channel first.")
    try:
        call("POST", f"/channels/{route['channel_id']}/messages", {"embeds": [{
            "title": "Tracewise is connected", "color": 0x30A46C,
            "description": f"Incidents in **{route['name']}** will be posted here, each with its own thread."}]})
    except DiscordError as exc:
        raise HTTPException(400, f"Discord said {exc}. Check the bot can see and post in that channel.")
    return {"sent": True}


@router.delete("/installation")
def uninstall(request: Request):
    ctx, inst = _install(request)
    try:
        call("DELETE", f"/users/@me/guilds/{inst['guild_id']}")  # the bot leaves the server
    except DiscordError:
        pass
    db.query("DELETE FROM discord_installations WHERE workspace_id = %s", ctx["workspace"]["id"])
    return {"removed": True}


# ---------------------------------------------------------------- messages

def incident_message(inc: dict, project: str) -> dict:
    label, _ = STATUS.get(inc["status"], (inc["status"], ""))
    url = f"{WEB_URL}/incidents/{inc['id']}"
    fields = [{"name": "Status", "value": label, "inline": True}, {"name": "Project", "value": project, "inline": True},
              {"name": "Severity", "value": inc["severity"], "inline": True}]
    if inc.get("acknowledged_by"):
        fields.append({"name": "Acknowledged by", "value": inc["acknowledged_by"], "inline": True})
    if inc["status"] == "resolved" and inc.get("root_cause"):
        desc = f"**Root cause:** {inc['root_cause']}\n**Fix:** {inc.get('fix') or '—'}"
    elif inc["status"] == "escalated":
        desc = (inc.get("summary") or "")[:1500]
    else:
        desc = "\n".join(f"`{s['service']}` {s['status']}" + (f" · errors {s['error_rate']:.0%}" if s.get("requests") else "")
                         for s in (inc.get("signals") or [])[:6])
    buttons = [{"type": 2, "style": 5, "label": "Open timeline", "url": url}]
    if not inc.get("acknowledged_by") and inc["status"] != "resolved":
        buttons.insert(0, {"type": 2, "style": 1, "label": "Acknowledge", "custom_id": f"ack:{inc['id']}"})
    return {"embeds": [{"title": f"Incident #{inc['id']}: {inc['title']}"[:256], "url": url, "description": desc[:4000],
                        "color": COLOR.get(inc["status"], 0x888888), "fields": fields}],
            "components": [{"type": 1, "components": buttons}]}


def approval_message(a: dict) -> dict:
    from .approvals import describe
    p = a.get("params") or {}
    title = {"pending": "Approval needed", "approved": "Approved", "rejected": "Rejected", "expired": "Expired"}[a["status"]]
    color = {"pending": 0xF5A524, "approved": 0x30A46C, "rejected": 0xE5484D, "expired": 0x888888}[a["status"]]
    desc = f"**{describe(a)}**" + (f"\n> {p['reason'][:1500]}" if p.get("reason") else "")
    if a["status"] != "pending":
        desc += f"\n{a.get('decided_by') or 'Nobody'}" + (f" via {a['decided_via']}" if a.get("decided_via") not in (None, "system") else "")
    msg = {"embeds": [{"title": title, "description": desc[:4000], "color": color}], "components": []}
    if a["status"] == "pending":
        msg["components"] = [{"type": 1, "components": [{"type": 2, "style": 5, "label": "Review & approve in Tracewise",
                                                         "url": f"{WEB_URL}/incidents/{a['incident_id']}"}]}]
    return msg


def step_text(step: dict) -> str | None:
    from .slack import step_text as slack_text
    text = slack_text(step)
    if not text:
        return None
    for emoji, plain in ((":zap:", "⚡"), (":wrench:", "🔧"), (":white_check_mark:", "✅"), (":hourglass:", "⏳"),
                         (":large_green_circle:", "🟢"), (":warning:", "⚠️"), (":rotating_light:", "🚨")):
        text = text.replace(emoji, plain)
    return text.replace("*", "**").replace("\n>", "\n> ")


def _route(inc: dict):
    route = db.one("SELECT r.*, p.workspace_id, p.name AS project FROM discord_routes r JOIN projects p ON p.id = r.project_id"
                   " WHERE r.project_id = %s", inc["project_id"])
    if route and db.one("SELECT 1 FROM discord_installations WHERE workspace_id = %s", route["workspace_id"]):
        return route
    return None


def refresh_root(incident_id: int) -> None:
    inc = db.one("SELECT * FROM incidents WHERE id = %s", incident_id)
    t = db.one("SELECT * FROM discord_threads WHERE incident_id = %s", incident_id)
    route = _route(inc) if inc else None
    if t and route:
        call("PATCH", f"/channels/{t['channel_id']}/messages/{t['message_id']}", incident_message(inc, route["project"]))


def post_step(step: dict) -> None:
    inc = db.one("SELECT * FROM incidents WHERE id = %s", step["incident_id"])
    route = _route(inc) if inc else None
    if not route:
        return
    from .slack import EVENT_OF
    event = EVENT_OF.get(step["kind"])
    t = db.one("SELECT * FROM discord_threads WHERE incident_id = %s", inc["id"])
    if not t:
        if "opened" not in route["events"] and event not in route["events"]:
            return
        m = call("POST", f"/channels/{route['channel_id']}/messages", incident_message(inc, route["project"]))
        thread = call("POST", f"/channels/{route['channel_id']}/messages/{m['id']}/threads",
                      {"name": f"#{inc['id']} {inc['title']}"[:100], "auto_archive_duration": 1440})
        db.query("INSERT INTO discord_threads (incident_id, channel_id, message_id, thread_id) VALUES (%s, %s, %s, %s)"
                 " ON CONFLICT DO NOTHING", inc["id"], route["channel_id"], m["id"], thread.get("id"))
        t = {"channel_id": route["channel_id"], "message_id": m["id"], "thread_id": thread.get("id")}
        if step["kind"] == "detector" and not step["title"].startswith("Also affected"):
            return
    where = t["thread_id"] or t["channel_id"]
    if step["kind"] == "approval":
        a = db.one("SELECT * FROM approvals WHERE id = %s", (step.get("data") or {}).get("approval_id"))
        if a and "approval" in route["events"]:
            m = call("POST", f"/channels/{where}/messages", approval_message(a))
            db.query("UPDATE approvals SET discord_channel = %s, discord_message = %s WHERE id = %s", where, m["id"], a["id"])
        return
    if step["kind"] == "approval_decision":
        a = db.one("SELECT * FROM approvals WHERE id = %s", (step.get("data") or {}).get("approval_id"))
        if a and a["discord_message"]:
            call("PATCH", f"/channels/{a['discord_channel']}/messages/{a['discord_message']}", approval_message(a))
        return
    text = step_text(step)
    if text and event in route["events"]:
        call("POST", f"/channels/{where}/messages", {"content": text[:1990]})
    call("PATCH", f"/channels/{t['channel_id']}/messages/{t['message_id']}", incident_message(inc, route["project"]))


def notifier_loop() -> None:
    if not db.one("SELECT 1 FROM discord_cursor WHERE id = 1"):
        db.query("INSERT INTO discord_cursor (id, step_id) SELECT 1, coalesce(max(id), 0) FROM incident_steps ON CONFLICT DO NOTHING")
    while True:
        try:
            cursor = db.one("SELECT step_id FROM discord_cursor WHERE id = 1")["step_id"]
            steps = db.query(
                "SELECT s.* FROM incident_steps s JOIN incidents i ON i.id = s.incident_id"
                " JOIN discord_routes r ON r.project_id = i.project_id WHERE s.id > %s"
                " AND s.kind IN ('detector', 'action', 'fix', 'verify', 'resolve', 'escalate', 'approval', 'approval_decision')"
                " AND NOT EXISTS (SELECT 1 FROM discord_posts p WHERE p.step_id = s.id) ORDER BY s.id LIMIT 50", cursor)
            for step in steps:
                try:
                    post_step(step)
                except DiscordError as exc:
                    log.warning("discord post for step %s failed: %s", step["id"], exc)
                db.query("INSERT INTO discord_posts (step_id) VALUES (%s) ON CONFLICT DO NOTHING", step["id"])
            if not steps:
                db.query("UPDATE discord_cursor SET step_id = (SELECT coalesce(max(id), 0) FROM incident_steps) WHERE id = 1")
        except Exception:
            log.exception("discord notifier")
        time.sleep(2)


def start_notifier() -> None:
    if configured():
        threading.Thread(target=notifier_loop, daemon=True, name="discord").start()


# ---------------------------------------------------------------- interactions from Discord

def verify(request: Request, body: bytes) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    sig, ts = request.headers.get("x-signature-ed25519", ""), request.headers.get("x-signature-timestamp", "")
    if not PUBLIC_KEY:
        log.warning("Discord interaction rejected: DISCORD_PUBLIC_KEY is not set on this server")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY)).verify(bytes.fromhex(sig), ts.encode() + body)
    except (InvalidSignature, ValueError):
        raise HTTPException(401, "invalid request signature")


def _ephemeral(text: str) -> JSONResponse:
    return JSONResponse({"type": 4, "data": {"content": text[:1990], "flags": 64}})


@router.post("/interactions")
async def interactions(request: Request):
    body = await request.body()
    verify(request, body)
    data = json.loads(body)
    if data.get("type") == 1:  # Discord checks the endpoint with a PING
        return JSONResponse({"type": 1})
    inst = db.one("SELECT * FROM discord_installations WHERE guild_id = %s ORDER BY created_at DESC LIMIT 1", data.get("guild_id", ""))
    if not inst:
        return _ephemeral("This Discord server isn't connected to Tracewise yet.")
    user = ((data.get("member") or {}).get("user") or data.get("user") or {})
    who = user.get("global_name") or user.get("username") or "someone"
    if data.get("type") == 3:
        custom = (data.get("data") or {}).get("custom_id", "")
        if custom.startswith("ack:"):
            inc = db.one("SELECT i.* FROM incidents i JOIN projects p ON p.id = i.project_id WHERE i.id = %s AND p.workspace_id = %s",
                         int(custom[4:]), inst["workspace_id"])
            if not inc:
                return _ephemeral("That incident isn't in this workspace.")
            if not inc["acknowledged_by"]:
                db.query("UPDATE incidents SET acknowledged_by = %s, acknowledged_at = now() WHERE id = %s", f"{who} (Discord)", inc["id"])
                db.add_step(inc["id"], "note", f"Acknowledged by {who} in Discord", {"text": f"Acknowledged by {who} in Discord"})
            inc = db.one("SELECT * FROM incidents WHERE id = %s", inc["id"])
            route = _route(inc)
            return JSONResponse({"type": 7, "data": incident_message(inc, route["project"] if route else "")})
        return _ephemeral("Unknown action.")
    if data.get("type") == 2:
        opts = {o["name"]: o.get("value") for o in (data.get("data") or {}).get("options", [])}
        view = opts.get("view") or "status"
        projects = db.query("SELECT * FROM projects WHERE workspace_id = %s ORDER BY created_at", inst["workspace_id"])
        if opts.get("project"):
            projects = [p for p in projects if p["slug"] == opts["project"]] or projects
        lines = []
        for p in projects[:5]:
            lines.append(f"**{p['name']}**")
            if view == "incidents":
                rows = db.query("SELECT id, title, status FROM incidents WHERE project_id = %s ORDER BY id DESC LIMIT 10", p["id"])
                lines += [f"[#{r['id']}]({WEB_URL}/incidents/{r['id']}) {r['title']} · {STATUS.get(r['status'], (r['status'],))[0]}" for r in rows] or ["No incidents yet."]
            else:
                from .health import snapshot
                snap = snapshot(p["id"])
                bad = [s for s in snap if s["status"] != "healthy"]
                lines.append(f"🟢 {len(snap)} services healthy" if not bad else
                             f"🔴 {len(bad)} of {len(snap)} unhealthy: " + ", ".join(f"`{s['service']}` {s['status']}" for s in bad[:8]))
                for r in db.query("SELECT id, title FROM incidents WHERE project_id = %s AND status IN"
                                  " ('open','investigating','acting','fixing','verifying') ORDER BY id DESC", p["id"]):
                    lines.append(f"🚨 [#{r['id']}]({WEB_URL}/incidents/{r['id']}) {r['title']} (agent working)")
        return _ephemeral("\n".join(lines) or "No projects yet.")
    return _ephemeral("Unsupported interaction.")
