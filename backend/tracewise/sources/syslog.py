"""Syslog (RFC 5424 and RFC 3164) parsing, plus Heroku-style logplex framing."""

import re
from datetime import datetime, timezone

from .model import guess_level, level_of

RFC5424 = re.compile(r"<(\d{1,3})>1 (\S+) (\S+) (\S+) (\S+) (\S+) (-|\[.*?\](?:\[.*?\])*) ?(.*)", re.S)
RFC3164 = re.compile(r"<(\d{1,3})>(\w{3} [ \d]\d \d\d:\d\d:\d\d) (\S+) ([^:\[\s]+)(?:\[(\d+)\])?: ?(.*)", re.S)


def parse(line: str, default_service: str | None = None) -> dict | None:
    line = line.rstrip("\r\n\x00")
    if not line.strip():
        return None
    m = RFC5424.match(line)
    if m:
        pri, ts, host, app, procid, msgid, _sd, msg = m.groups()
        sev = int(pri) & 7
        msg = msg.lstrip("\ufeff")
        return {"service": default_service or (app if app != "-" else host), "ts": None if ts == "-" else ts,
                "level": _level(sev, msg), "message": msg,
                "fields": {"host": host, "procid": procid, "msgid": msgid}}
    m = RFC3164.match(line)
    if m:
        pri, ts, host, app, pid, msg = m.groups()
        sev = int(pri) & 7
        try:
            dt = datetime.strptime(f"{datetime.now().year} {ts}", "%Y %b %d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            dt = None
        return {"service": default_service or app, "ts": dt, "level": _level(sev, msg),
                "message": msg, "fields": {"host": host, "pid": pid}}
    return {"service": default_service or "syslog", "ts": None, "level": guess_level(line),
            "message": line}


def _level(sev: int, msg: str) -> str:
    # Many apps log everything at "info"/"notice" and put the real level in the text.
    by_pri = level_of(sev, scheme="syslog")
    by_text = guess_level(msg)
    order = ("debug", "info", "warning", "error", "critical")
    return by_text if order.index(by_text) > order.index(by_pri) else by_pri


def logplex(body: str, default_service: str | None = None) -> list[dict]:
    """Heroku log drains (and others using octet-counted RFC 6587 framing)."""
    out, i = [], 0
    while i < len(body):
        sp = body.find(" ", i)
        if sp == -1 or not body[i:sp].isdigit():
            out.extend(filter(None, (parse(l, default_service) for l in body[i:].splitlines())))
            break
        n = int(body[i:sp])
        frame = body[sp + 1: sp + 1 + n]
        i = sp + 1 + n
        rec = parse(frame, default_service)
        if rec:
            out.append(rec)
    return out
