"""The common shape every connector turns its data into, and how it's stored.

A connector produces plain dicts:
- log:    service, ts, level, message, [trace, route, status, sha, count, fields]
- metric: service, ts, count, errors, p50_ms, p95_ms, max_ms, [sha]   (one window of requests)
- event:  service, kind, severity, status, title, [fingerprint, ts, active_until, detail]
- deploy: service, sha, [prev_sha, author, message, actor, reason, deployed_at]
"""

import re
import time
from datetime import datetime, timedelta, timezone

from .. import db

LEVELS = ("debug", "info", "warning", "error", "critical")
RANK = {name: i for i, name in enumerate(LEVELS)}
ERRORISH = ("error", "critical")

_LEVEL_NAMES = {
    "trace": "debug", "debug": "debug", "dbg": "debug", "verbose": "debug", "fine": "debug",
    "finer": "debug", "finest": "debug", "d": "debug",
    "info": "info", "information": "info", "informational": "info", "notice": "info",
    "inf": "info", "log": "info", "default": "info", "ok": "info", "success": "info", "i": "info",
    "config": "info", "out": "info", "stdout": "info",
    "warn": "warning", "warning": "warning", "wrn": "warning", "w": "warning",
    "error": "error", "err": "error", "eror": "error", "severe": "error", "fail": "error",
    "failure": "error", "e": "error", "exception": "error",
    "critical": "critical", "crit": "critical", "fatal": "critical", "panic": "critical",
    "emerg": "critical", "emergency": "critical", "alert": "critical", "f": "critical",
}
_SYSLOG = ["critical", "critical", "critical", "error", "warning", "info", "info", "debug"]
_PINO = {10: "debug", 20: "debug", 30: "info", 40: "warning", 50: "error", 60: "critical"}

_GUESS = [
    (re.compile(r"\b(FATAL|PANIC|CRITICAL|EMERG(?:ENCY)?)\b|^panic: |\[(crit|alert|emerg)\]"),
     "critical"),
    (re.compile(r"\b(ERROR|ERR|SEVERE)\b|Traceback \(most recent call last\)|"
                r"\b(Uncaught|Unhandled)\b|\b(?:[A-Z]\w*)?(Error|Exception)\b:|\[error\]|"
                r"(?i:\blevel[=:]\s*\"?(error|err|fatal|critical)\b)"), "error"),
    (re.compile(r"\bWARN(ING)?\b|\[warn\]|(?i:\blevel[=:]\s*\"?warn)"), "warning"),
    (re.compile(r"\bDEBUG\b|\bTRACE\b"), "debug"),
]


def level_of(value=None, message: str = "", scheme: str | None = None) -> str:
    """Normalise a level from any convention (names, syslog 0-7, OTel 1-24, pino 10-60)."""
    if value is None or value == "":
        return guess_level(message)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _LEVEL_NAMES:
            return _LEVEL_NAMES[v]
        if v.startswith("sev") and v[3:].isdigit():  # Azure Sev0 (critical) .. Sev4 (verbose)
            return ["critical", "error", "warning", "info", "debug"][min(int(v[3:]), 4)]
        if v.lstrip("-").isdigit():
            value = int(v)
        else:
            for name, level in _LEVEL_NAMES.items():
                if len(name) > 2 and v.startswith(name):
                    return level
            return guess_level(message)
    if isinstance(value, bool):
        return "error" if value else "info"
    if isinstance(value, (int, float)):
        n = int(value)
        if scheme == "syslog" or (scheme is None and 0 <= n <= 7):
            return _SYSLOG[max(0, min(n, 7))]
        if scheme == "pino" or (scheme is None and n in _PINO):
            return _PINO.get(n, "info")
        if scheme == "otel" or (scheme is None and 1 <= n <= 24):
            return ("debug", "debug", "info", "warning", "error", "critical")[min((n - 1) // 4, 5)] \
                if n > 0 else guess_level(message)
    return guess_level(message)


def guess_level(message: str) -> str:
    head = (message or "")[:400]
    for pattern, level in _GUESS:
        if pattern.search(head):
            return level
    if "Traceback (most recent call last)" in (message or ""):
        return "error"
    return "info"


def severity_of(value, default: str = "error") -> str:
    """Alert severity from the many conventions (P1, Sev2, high, page, disaster...)."""
    if value is None or value == "":
        return default
    v = str(value).strip().lower().replace(" ", "")
    table = {
        "critical": "critical", "crit": "critical", "page": "critical", "p1": "critical",
        "p0": "critical", "sev0": "critical", "sev1": "critical", "high": "critical",
        "fatal": "critical", "disaster": "critical", "emergency": "critical", "urgent": "critical",
        "error": "error", "major": "error", "p2": "error", "sev2": "error", "average": "error",
        "warning": "warning", "warn": "warning", "minor": "warning", "p3": "warning",
        "sev3": "warning", "medium": "warning",
        "info": "info", "information": "info", "p4": "info", "p5": "info", "low": "info",
        "sev4": "info", "none": "info", "nonseverity": "info", "ok": "info",
    }
    return table.get(v, default)


_FRACTION = re.compile(r"(\.\d{6})\d+")
_CLF = "%d/%b/%Y:%H:%M:%S %z"


def to_ts(value=None) -> datetime:
    """Seconds/ms/µs/ns epochs, ISO 8601 (any precision), RFC 3339 and common-log timestamps."""
    now = datetime.now(timezone.utc)
    if value is None or value == "":
        return now
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, (int, float)) or (isinstance(value, str)
                                             and re.fullmatch(r"\d+(\.\d+)?", value.strip())):
        x = float(value)
        x = x / 1e9 if x > 1e17 else x / 1e6 if x > 1e14 else x / 1e3 if x > 1e11 else x
        dt = datetime.fromtimestamp(x, tz=timezone.utc)
    elif isinstance(value, dict) and "seconds" in value:  # protobuf Timestamp as JSON
        dt = datetime.fromtimestamp(int(value["seconds"]) + int(value.get("nanos", 0)) / 1e9,
                                    tz=timezone.utc)
    else:
        s = str(value).strip()
        try:
            dt = datetime.fromisoformat(_FRACTION.sub(r"\1", s.replace("Z", "+00:00")))
        except ValueError:
            try:
                dt = datetime.strptime(s, _CLF)
            except ValueError:
                return now
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
    return min(dt, now + timedelta(seconds=5))  # clocks drift; never store the future


_PY_TB = "Traceback (most recent call last)"
_FRAME = re.compile(r"\n\s+at [\w$.<>\[\]/:@-]+|\ngoroutine \d+ \[")


def split_trace(message: str) -> tuple[str, str | None]:
    """Separate a multi-line stack trace from its headline (the line people search for)."""
    if not message or "\n" not in message:
        return message, None
    if _PY_TB in message:
        tail = [l for l in message[message.index(_PY_TB):].splitlines()
                if l.strip() and not l.startswith((" ", "\t"))]
        headline = tail[-1] if len(tail) > 1 else message.splitlines()[0]
        return headline.strip()[:2000], message[-6000:]
    if _FRAME.search(message):
        return message.splitlines()[0].strip()[:2000], message[-6000:]
    return message, None


def service_name(value) -> str:
    s = re.sub(r"\s+", "-", str(value or "").strip())[:100]
    return s or "unknown"


def first(d: dict, *keys, default=None, scalar: bool = True):
    """The first present key; keys may be dotted paths into nested dicts or literal dotted keys."""
    for key in keys:
        if not key:
            continue
        if key in d and d[key] not in (None, "") and not (scalar and isinstance(d[key], (dict, list))):
            return d[key]
        cur = d
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                cur = None
                break
            cur = cur[part]
        if cur not in (None, "") and not (scalar and isinstance(cur, (dict, list))):
            return cur
    return default


SERVICE_KEYS = ("service", "service.name", "service_name", "serviceName", "app", "app_name",
                "application", "appName", "component", "job", "kubernetes.labels.app",
                "kubernetes.labels.app.kubernetes.io/name", "k8s.deployment.name",
                "kubernetes.container_name", "container_name", "container.name",
                "compose_service", "syslog.appname", "appname", "program", "logger", "host",
                "hostname")
MESSAGE_KEYS = ("message", "msg", "log", "text", "body", "Body", "line", "_raw", "event",
                "error.message", "short_message", "full_message", "MESSAGE")
LEVEL_KEYS = ("level", "severity", "log.level", "lvl", "loglevel", "levelname", "status",
              "severity_text", "SeverityText", "level_name", "PRIORITY", "detected_level")
TS_KEYS = ("ts", "timestamp", "@timestamp", "time", "datetime", "date", "_time", "eventTime",
           "TimeGenerated", "__REALTIME_TIMESTAMP", "t")
TRACE_KEYS = ("trace", "stack", "stacktrace", "stack_trace", "error.stack", "error.stack_trace",
              "exception", "exception.stacktrace", "exc_info", "err.stack")


def log_from_dict(d: dict, service: str | None = None, default_level: str | None = None) -> dict:
    """Map an arbitrary structured log record onto ours, whatever the field names are."""
    message = first(d, *MESSAGE_KEYS, default="", scalar=False)
    if isinstance(message, (dict, list)):
        import json
        message = json.dumps(message)[:4000]
    message = str(message)
    trace = first(d, *TRACE_KEYS, scalar=False)
    if trace is not None and not isinstance(trace, str):
        import json
        trace = json.dumps(trace)[:6000]
    if not trace:
        message, trace = split_trace(message)
    raw_level = first(d, *LEVEL_KEYS)
    if raw_level is None and default_level:
        raw_level = default_level
    level = level_of(raw_level, message + "\n" + (trace or ""))
    if trace and level in ("debug", "info"):
        level = "error"
    status = first(d, "status_code", "statusCode", "http.status_code", "http.response.status_code",
                   "response_code", "http_status")
    route = first(d, "route", "path", "url.path", "http.route", "http.target", "request_path")
    known = set(MESSAGE_KEYS + LEVEL_KEYS + TS_KEYS + TRACE_KEYS + SERVICE_KEYS)
    fields = {k: v for k, v in d.items() if k not in known and not isinstance(v, (dict, list))}
    if isinstance(d.get("fields"), dict):  # already-normalised records (host agent, our own API)
        fields.update({k: v for k, v in d["fields"].items() if not isinstance(v, (dict, list))})
    fields.pop("fields", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    return {"service": service or first(d, *SERVICE_KEYS) or "unknown",
            "ts": first(d, *TS_KEYS), "level": level, "message": message, "trace": trace,
            "route": str(route)[:300] if route else None, "status": status,
            "sha": first(d, "sha", "commit", "git.commit.sha", "version", "service.version"),
            "count": int(first(d, "count", default=1)) if str(first(d, "count", default=1)).isdigit() else 1,
            "fields": dict(list(fields.items())[:30])}


# ---------- storage ----------

def register(kind: str, name: str, mode: str = "push") -> int:
    """Record that a push source exists (it shows up in the sources list from its first batch)."""
    row = db.one(
        "INSERT INTO sources (kind, name, mode, status) VALUES (%s, %s, %s, 'receiving')"
        " ON CONFLICT (kind, name) DO UPDATE SET last_received_at = now() RETURNING id",
        kind, name[:120], mode)
    return row["id"]


def store(source: str, logs=(), metrics=(), events=(), deploys=(), edges=(),
          source_id: int | None = None) -> dict:
    logs, metrics, events, deploys, edges = (list(logs), list(metrics), list(events), list(deploys),
                                             list(edges))
    services = {service_name(x.get("service")) for x in logs + metrics + events + deploys}
    services |= {service_name(e[k]) for e in edges for k in ("src", "dst")}
    if services:
        # One statement in a fixed order: concurrent writers lock rows in the same order and
        # can't deadlock.
        db.query("INSERT INTO services (name) SELECT unnest(%s::text[]) ORDER BY 1"
                 " ON CONFLICT (name) DO UPDATE SET last_seen = now()", sorted(services))

    rows = []
    for l in logs:
        message, trace = l.get("message") or "", l.get("trace")
        if not trace:
            message, trace = split_trace(message)
        rows.append((service_name(l.get("service")), to_ts(l.get("ts")), l.get("sha"),
                     l.get("level") or guess_level(message), message[:4000] or "(empty)",
                     l.get("route"), l.get("status"), (trace or None) and trace[-6000:],
                     db.jsonb(l.get("fields") or {}), source, max(1, int(l.get("count") or 1))))
    db.many("INSERT INTO log_events (service, ts, sha, level, message, route, status, trace, fields,"
            " source, count) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", rows)

    db.many("INSERT INTO metric_points (service, ts, sha, count, errors, p50_ms, p95_ms, max_ms,"
            " source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [(service_name(m["service"]), to_ts(m.get("ts")), m.get("sha"), int(m.get("count") or 0),
              int(m.get("errors") or 0), float(m.get("p50_ms") or 0), float(m.get("p95_ms") or 0),
              float(m.get("max_ms") or m.get("p95_ms") or 0), source) for m in metrics])
    for m in metrics:
        if m.get("sha"):
            db.query("UPDATE services SET current_sha = %s WHERE name = %s", m["sha"],
                     service_name(m["service"]))

    for e in edges:
        src, dst = service_name(e["src"]), service_name(e["dst"])
        db.query("INSERT INTO service_edges (src, dst, calls, errors) VALUES (%s, %s, %s, %s)"
                 " ON CONFLICT (src, dst) DO UPDATE SET calls = service_edges.calls + EXCLUDED.calls,"
                 " errors = service_edges.errors + EXCLUDED.errors, last_seen = now()",
                 src, dst, int(e["calls"]), int(e["errors"]))
        db.query("INSERT INTO edge_points (src, dst, ts, calls, errors, avg_ms)"
                 " VALUES (%s, %s, %s, %s, %s, %s)", src, dst, to_ts(e.get("ts")), int(e["calls"]),
                 int(e["errors"]), float(e.get("avg_ms") or 0))

    for e in events:
        upsert_event(source, e)

    for d in deploys:
        row = db.one(
            "INSERT INTO deploys (service, sha, prev_sha, author, author_email, message,"
            " committed_at, actor, reason, deployed_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            service_name(d["service"]), str(d["sha"])[:80], d.get("prev_sha"), d.get("author"),
            d.get("author_email"), (d.get("message") or "")[:2000] or None,
            d.get("committed_at"), d.get("actor") or source, d.get("reason"),
            to_ts(d.get("deployed_at")))
        db.query("UPDATE services SET current_sha = %s WHERE name = %s", str(d["sha"])[:80],
                 service_name(d["service"]))
        db.notify("system_events", {"type": "deploy", "deploy_id": row["id"],
                                    "service": service_name(d["service"]), "sha": d["sha"]})

    n = len(logs) + len(metrics) + len(events) + len(deploys) + len(edges)
    if source_id and n:
        db.query("UPDATE sources SET items_received = items_received + %s, last_received_at = now()"
                 " WHERE id = %s", n, source_id)
    return {"logs": len(logs), "metrics": len(metrics), "events": len(events),
            "deploys": len(deploys), "edges": len(edges)}


ONE_SHOT = ("crash", "restart", "oom", "deploy_failed", "info")


def upsert_event(source: str, e: dict) -> None:
    ts = to_ts(e.get("ts"))
    kind = e.get("kind") or "alert"
    status = "resolved" if str(e.get("status", "firing")).lower() in (
        "resolved", "ok", "closed", "recovered", "inactive") else "firing"
    severity = severity_of(e.get("severity"), "error")
    service = service_name(e.get("service"))
    if status == "resolved":
        active_until = datetime.now(timezone.utc)
    elif e.get("sticky"):  # a state (crash loop, failed unit) that holds until it's resolved
        active_until = datetime.now(timezone.utc) + timedelta(hours=24)
    elif e.get("active_until"):
        active_until = to_ts(e["active_until"]) if not isinstance(e["active_until"], datetime) \
            else e["active_until"]
        if active_until <= datetime.now(timezone.utc):  # e.g. Alertmanager endsAt already passed
            active_until = datetime.now(timezone.utc) + timedelta(minutes=5)
    else:
        active_until = ts + timedelta(minutes=3 if kind in ONE_SHOT else 15)
    fingerprint = str(e.get("fingerprint") or (
        f"{kind}:{service}:{int(ts.timestamp())}" if kind in ONE_SHOT
        else f"{kind}:{service}:{e.get('title')}"))[:300]
    row = db.one(
        """INSERT INTO source_events (source, service, fingerprint, kind, severity, status, title,
                                      detail, started_at, last_seen, active_until)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
           ON CONFLICT (source, fingerprint) DO UPDATE SET
               status = EXCLUDED.status, severity = EXCLUDED.severity, title = EXCLUDED.title,
               detail = EXCLUDED.detail, last_seen = now(), active_until = EXCLUDED.active_until,
               started_at = CASE WHEN source_events.status = 'resolved' AND EXCLUDED.status = 'firing'
                                 THEN EXCLUDED.started_at ELSE source_events.started_at END,
               incident_id = CASE WHEN source_events.status = 'resolved' AND EXCLUDED.status = 'firing'
                                  THEN NULL ELSE source_events.incident_id END
           RETURNING id, (xmax = 0) AS inserted""",
        source, service, fingerprint, kind, severity, status, str(e.get("title") or kind)[:500],
        db.jsonb(e.get("detail") or {}), ts, active_until)
    db.notify("system_events", {"type": "source_event", "event_id": row["id"], "service": service,
                                "status": status, "severity": severity})


def now_ts() -> float:
    return time.time()
