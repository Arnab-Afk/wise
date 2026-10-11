"""Sign-in: one-time email codes, Google and GitHub OAuth, and sessions.

Sessions are opaque random tokens; only their HMAC is stored. The web app keeps the token in an
httpOnly cookie and sends it to the API as a bearer token. Every /v1 route except ingest, sign-in
and invite previews needs a session (or the ingest key, for scripts and internal tools).
"""

import hashlib
import hmac
import os
import re
import secrets as pysecrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import config, db, emails

router = APIRouter(prefix="/v1/auth")

SESSION_DAYS = 30
OTP_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
_KEY = (os.environ.get("TW_SECRET_KEY") or config.INGEST_KEY or "tracewise-dev").encode()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES = ("viewer", "member", "admin", "owner")

PROVIDERS = {
    "google": {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
    },
    "github": {
        "client_id": os.environ.get("GITHUB_CLIENT_ID", ""),
        "client_secret": os.environ.get("GITHUB_CLIENT_SECRET", ""),
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
    },
}


def digest(value: str) -> str:
    return hmac.new(_KEY, value.encode(), hashlib.sha256).hexdigest()


def rank(role: str | None) -> int:
    return ROLES.index(role) if role in ROLES else -1


def client_ip(request: Request) -> str | None:
    h = request.headers
    ip = h.get("cf-connecting-ip") or h.get("x-real-ip") or (h.get("x-forwarded-for") or "").split(",")[0].strip()
    return ip or (request.client.host if request.client else None)


def normalise_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(400, "Enter a valid email address.")
    return email


# ---------------------------------------------------------------- sessions

def resolve(request: Request) -> dict | None:
    """The signed-in user, their workspace and role, from the bearer token (or None)."""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else request.cookies.get("tw_session")
    if not token:
        return None
    row = db.one(
        "SELECT s.id AS session_id, s.last_seen_at, u.* FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > now()", digest(token))
    if not row:
        return None
    if (datetime.now(timezone.utc) - row["last_seen_at"]).total_seconds() > 60:
        db.query("UPDATE sessions SET last_seen_at = now() WHERE id = %s", row["session_id"])
    wanted = request.headers.get("x-tracewise-workspace")
    membership = db.one(
        "SELECT w.id, w.name, w.slug, m.role FROM workspace_members m JOIN workspaces w ON w.id = m.workspace_id"
        " WHERE m.user_id = %s AND (%s::bigint IS NULL OR w.id = %s::bigint) ORDER BY m.created_at LIMIT 1",
        row["id"], wanted if (wanted or "").isdigit() else None, wanted if (wanted or "").isdigit() else None)
    return {"user": {k: row[k] for k in ("id", "email", "name", "avatar_url", "notify_incidents")},
            "session_id": row["session_id"], "workspace": membership,
            "role": membership["role"] if membership else None}


def require(request: Request, role: str | None = None) -> dict:
    ctx = getattr(request.state, "auth", None) or resolve(request)
    if not ctx:
        raise HTTPException(401, "Sign in required.")
    if role and rank(ctx["role"]) < rank(role):
        raise HTTPException(403, f"You need to be {role} or above to do that.")
    return ctx


def start_session(user: dict, method: str, request: Request) -> str:
    token = pysecrets.token_urlsafe(32)
    ua = (request.headers.get("user-agent") or "")[:300]
    ip = client_ip(request)
    seen_before = db.one("SELECT 1 FROM sessions WHERE user_id = %s AND user_agent = %s"
                         " AND created_at > now() - interval '60 days' LIMIT 1", user["id"], ua)
    had_sessions = db.one("SELECT 1 FROM sessions WHERE user_id = %s LIMIT 1", user["id"])
    db.query("INSERT INTO sessions (token_hash, user_id, method, ip, user_agent, expires_at)"
             " VALUES (%s, %s, %s, %s, %s, now() + make_interval(days => %s))",
             digest(token), user["id"], method, ip, ua, SESSION_DAYS)
    db.query("UPDATE users SET last_login_at = now() WHERE id = %s", user["id"])
    if had_sessions and not seen_before:
        emails.new_sign_in(user["email"], {"email": "email code", "google": "Google", "github": "GitHub"}[method],
                           ip, ua, datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC"))
    return token


def upsert_user(email: str, name: str | None = None, avatar: str | None = None) -> tuple[dict, bool]:
    user = db.one("SELECT * FROM users WHERE email = %s", email)
    if user:
        if (name and not user["name"]) or (avatar and not user["avatar_url"]):
            user = db.one("UPDATE users SET name = coalesce(name, %s), avatar_url = coalesce(avatar_url, %s)"
                          " WHERE id = %s RETURNING *", name, avatar, user["id"])
        return user, False
    user = db.one("INSERT INTO users (email, name, avatar_url) VALUES (%s, %s, %s) RETURNING *", email, name, avatar)
    emails.welcome(email, name)
    return user, True


def signed_in(user: dict, is_new: bool, method: str, request: Request) -> dict:
    token = start_session(user, method, request)
    has_workspace = bool(db.one("SELECT 1 FROM workspace_members WHERE user_id = %s", user["id"]))
    return {"token": token, "expires_days": SESSION_DAYS, "new_user": is_new, "has_workspace": has_workspace,
            "user": {k: user[k] for k in ("id", "email", "name", "avatar_url")}}


# ---------------------------------------------------------------- email codes

@router.post("/otp/start")
def otp_start(body: dict, request: Request):
    email = normalise_email(body.get("email", ""))
    ip = client_ip(request)
    recent = db.one("SELECT count(*) AS n FROM otp_codes WHERE email = %s AND created_at > now() - interval '15 minutes'", email)
    by_ip = db.one("SELECT count(*) AS n FROM otp_codes WHERE ip = %s AND created_at > now() - interval '15 minutes'", ip)
    if recent["n"] >= 5 or by_ip["n"] >= 20:
        raise HTTPException(429, "Too many codes requested. Wait a few minutes and try again.")
    code = f"{pysecrets.randbelow(1_000_000):06d}"
    db.query("UPDATE otp_codes SET consumed_at = now() WHERE email = %s AND consumed_at IS NULL", email)
    db.query("INSERT INTO otp_codes (email, code_hash, ip, expires_at)"
             " VALUES (%s, %s, %s, now() + make_interval(mins => %s))", email, digest(f"{email}:{code}"), ip, OTP_MINUTES)
    emails.sign_in_code(email, code, ip, OTP_MINUTES)
    return {"sent": True, "expires_minutes": OTP_MINUTES}


@router.post("/otp/verify")
def otp_verify(body: dict, request: Request):
    email = normalise_email(body.get("email", ""))
    code = re.sub(r"\D", "", str(body.get("code", "")))
    row = db.one("SELECT * FROM otp_codes WHERE email = %s AND consumed_at IS NULL AND expires_at > now()"
                 " ORDER BY id DESC LIMIT 1", email)
    if not row:
        raise HTTPException(400, "That code has expired. Request a new one.")
    if row["attempts"] >= OTP_MAX_ATTEMPTS:
        raise HTTPException(429, "Too many wrong codes. Request a new one.")
    if not hmac.compare_digest(row["code_hash"], digest(f"{email}:{code}")):
        db.query("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = %s", row["id"])
        left = OTP_MAX_ATTEMPTS - row["attempts"] - 1
        raise HTTPException(400, f"That code isn't right. {left} {'try' if left == 1 else 'tries'} left.")
    db.query("UPDATE otp_codes SET consumed_at = now() WHERE id = %s", row["id"])
    user, is_new = upsert_user(email)
    return signed_in(user, is_new, "email", request)


# ---------------------------------------------------------------- Google and GitHub

@router.get("/providers")
def providers():
    return {name: bool(p["client_id"] and p["client_secret"]) for name, p in PROVIDERS.items()}


def provider(name: str) -> dict:
    p = PROVIDERS.get(name)
    if not p:
        raise HTTPException(404, "Unknown sign-in provider.")
    if not (p["client_id"] and p["client_secret"]):
        raise HTTPException(503, f"{name.title()} sign-in isn't configured yet.")
    return p


@router.post("/oauth/{name}/url")
def oauth_url(name: str, body: dict):
    p = provider(name)
    params = {"client_id": p["client_id"], "redirect_uri": body["redirect_uri"], "scope": p["scope"],
              "state": body["state"], "response_type": "code"}
    if name == "google":
        params.update(access_type="online", prompt="select_account")
    return {"url": f"{p['authorize']}?{urlencode(params)}"}


def _profile(name: str, p: dict, code: str, redirect_uri: str) -> dict:
    with httpx.Client(timeout=15, headers={"Accept": "application/json", "User-Agent": "Tracewise"}) as c:
        tok = c.post(p["token"], data={"client_id": p["client_id"], "client_secret": p["client_secret"],
                                       "code": code, "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        access = tok.json().get("access_token") if tok.status_code == 200 else None
        if not access:
            raise HTTPException(400, f"{name.title()} didn't accept the sign-in. Try again.")
        auth = {"Authorization": f"Bearer {access}"}
        if name == "google":
            info = c.get("https://openidconnect.googleapis.com/v1/userinfo", headers=auth).json()
            if not info.get("email_verified"):
                raise HTTPException(400, "Your Google email isn't verified.")
            return {"id": info["sub"], "email": info["email"].lower(), "name": info.get("name"),
                    "avatar": info.get("picture")}
        user = c.get("https://api.github.com/user", headers=auth).json()
        addresses = c.get("https://api.github.com/user/emails", headers=auth).json()
        primary = next((e["email"] for e in addresses if isinstance(e, dict) and e.get("primary") and e.get("verified")), None)
        if not primary:
            raise HTTPException(400, "Your GitHub account has no verified primary email.")
        return {"id": str(user["id"]), "email": primary.lower(), "name": user.get("name") or user.get("login"),
                "avatar": user.get("avatar_url")}


@router.post("/oauth/{name}/callback")
def oauth_callback(name: str, body: dict, request: Request):
    p = provider(name)
    prof = _profile(name, p, body["code"], body["redirect_uri"])
    linked = db.one("SELECT user_id FROM auth_identities WHERE provider = %s AND provider_user_id = %s", name, prof["id"])
    if linked:
        user, is_new = db.one("SELECT * FROM users WHERE id = %s", linked["user_id"]), False
    else:
        user, is_new = upsert_user(prof["email"], prof["name"], prof["avatar"])
        db.query("INSERT INTO auth_identities (provider, provider_user_id, user_id, email) VALUES (%s, %s, %s, %s)",
                 name, prof["id"], user["id"], prof["email"])
        if not is_new:
            emails.account_linked(user["email"], name)
    return signed_in(user, is_new, name, request)


# ---------------------------------------------------------------- the signed-in user

@router.get("/me")
def me(request: Request):
    ctx = require(request)
    workspaces = db.query(
        "SELECT w.id, w.name, w.slug, m.role FROM workspace_members m JOIN workspaces w ON w.id = m.workspace_id"
        " WHERE m.user_id = %s ORDER BY m.created_at", ctx["user"]["id"])
    identities = [r["provider"] for r in db.query("SELECT provider FROM auth_identities WHERE user_id = %s", ctx["user"]["id"])]
    return {**ctx["user"], "workspace": ctx["workspace"], "role": ctx["role"], "workspaces": workspaces,
            "linked": identities}


@router.patch("/me")
def update_me(body: dict, request: Request):
    ctx = require(request)
    if "notify_incidents" in body and body["notify_incidents"] not in ("all", "escalations", "none"):
        raise HTTPException(400, "notify_incidents must be all, escalations or none")
    return db.one("UPDATE users SET name = coalesce(%s, name), notify_incidents = coalesce(%s, notify_incidents)"
                  " WHERE id = %s RETURNING id, email, name, avatar_url, notify_incidents",
                  (body.get("name") or "").strip()[:80] or None, body.get("notify_incidents"), ctx["user"]["id"])


@router.get("/sessions")
def list_sessions(request: Request):
    ctx = require(request)
    rows = db.query("SELECT id, method, ip, user_agent, created_at, last_seen_at FROM sessions"
                    " WHERE user_id = %s AND revoked_at IS NULL AND expires_at > now() ORDER BY last_seen_at DESC",
                    ctx["user"]["id"])
    for r in rows:
        r["current"] = r["id"] == ctx["session_id"]
    return rows


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: int, request: Request):
    ctx = require(request)
    db.query("UPDATE sessions SET revoked_at = now() WHERE id = %s AND user_id = %s", session_id, ctx["user"]["id"])
    return {"revoked": True}


@router.post("/logout")
def logout(request: Request):
    ctx = resolve(request)
    if ctx:
        db.query("UPDATE sessions SET revoked_at = now() WHERE id = %s", ctx["session_id"])
    return {"ok": True}
