"""Collector: polls pull sources (Prometheus, Loki, Datadog...) and listens for syslog.

Each pull source is polled on its own interval, under a short lease so two collectors never poll
the same source at once. The poll cursor is saved with the source, so a restart carries on from
where it stopped.
"""

import json
import logging
import os
import socket
import socketserver
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import re

from . import db, secrets, tenancy
from .sources import syslog
from .sources.model import register, store
from .sources.pull import KINDS, SourceError

log = logging.getLogger("tracewise.collector")
SYSLOG_PORT = int(os.environ.get("TW_SYSLOG_PORT", "5514"))
MAX_PARALLEL = 8


def instance(row: dict):
    sec = json.loads(secrets.decrypt(row["credential"])) if row.get("credential") else {}
    cfg = dict(row["config"])
    cfg.setdefault("interval_seconds", interval_of(row))
    return KINDS[row["kind"]](cfg, sec)


def interval_of(row: dict) -> int:
    return int((row.get("config") or {}).get("interval_seconds") or KINDS[row["kind"]].interval)


def test_sources() -> None:
    for row in db.query("SELECT * FROM sources WHERE mode = 'pull' AND status = 'testing'"):
        try:
            detail, ok = instance(row).test(), True
        except SourceError as exc:
            detail, ok = str(exc), False
        except Exception as exc:
            detail, ok = f"{type(exc).__name__}: {exc}", False
        db.query("UPDATE sources SET status = %s, status_detail = %s, state = '{}' WHERE id = %s",
                 "ok" if ok else "failed", detail[:1000], row["id"])
        log.info("tested %s %s: %s", row["kind"], row["name"], detail[:200])


def due() -> list[dict]:
    rows = []
    for row in db.query("SELECT id, kind, config FROM sources WHERE mode = 'pull' AND enabled"
                        " AND status = 'ok' AND (poll_lease_until IS NULL OR poll_lease_until < now())"
                        " AND (last_polled_at IS NULL OR last_polled_at < now() - make_interval(secs =>"
                        " coalesce((config->>'interval_seconds')::int, %s)))", 5):
        if row["kind"] not in KINDS:
            continue
        claimed = db.one("UPDATE sources SET poll_lease_until = now() + interval '60 seconds'"
                         " WHERE id = %s AND (poll_lease_until IS NULL OR poll_lease_until < now())"
                         " AND (last_polled_at IS NULL OR last_polled_at < now() - make_interval(secs => %s))"
                         " RETURNING *", row["id"], interval_of(row))
        if claimed:
            rows.append(claimed)
    return rows


def poll(row: dict) -> None:
    started = time.time()
    try:
        records, state = instance(row).poll(dict(row["state"] or {}))
        counts = store(f"{row['kind']}:{row['name']}", row["project_id"], source_id=row["id"], **records)
        db.query("UPDATE sources SET state = %s, last_polled_at = now(), poll_lease_until = NULL,"
                 " status_detail = %s WHERE id = %s", db.jsonb(state),
                 f"Last poll {time.time() - started:.1f}s: " + ", ".join(
                     f"{v} {k}" for k, v in counts.items() if v) if any(counts.values())
                 else f"Last poll {time.time() - started:.1f}s: nothing new", row["id"])
    except Exception as exc:
        log.warning("poll %s %s failed: %s", row["kind"], row["name"], exc)
        db.query("UPDATE sources SET last_polled_at = now(), poll_lease_until = NULL,"
                 " status_detail = %s WHERE id = %s", f"Last poll failed: {exc}"[:1000], row["id"])


# ---------- syslog ----------

KEY_RE = re.compile(r"\b(twk_[A-Za-z0-9_-]{20,})\b")


class SyslogBuffer:
    """Syslog has no headers, so each line carries its project key, Papertrail-style: anywhere in the
    line or in structured data like [tracewise key="twk_..."]. Lines without a valid key are dropped."""

    def __init__(self):
        self.lock = threading.Lock()
        self.items: dict[int, list[dict]] = {}
        self.dropped = 0

    def add(self, line: str):
        m = KEY_RE.search(line)
        project = tenancy.project_for_key(m.group(1)) if m else None
        if not project:
            self.dropped += 1
            return
        line = KEY_RE.sub("", line).replace('[tracewise key=""]', "").replace("  ", " ")
        rec = syslog.parse(line)
        if rec:
            with self.lock:
                bucket = self.items.setdefault(project["id"], [])
                if len(bucket) < 20000:
                    bucket.append(rec)

    def flush_forever(self):
        while True:
            time.sleep(2)
            with self.lock:
                batches, self.items = self.items, {}
            for project_id, items in batches.items():
                try:
                    store("syslog", project_id, logs=items, source_id=register("syslog", "syslog", project_id))
                except Exception:
                    log.exception("syslog flush failed")


buffer = SyslogBuffer()


class UDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        buffer.add(self.request[0].decode("utf-8", "replace"))


class TCPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        while True:
            line = self.rfile.readline(65536)
            if not line:
                return
            text = line.decode("utf-8", "replace")
            head = text.split(" ", 1)[0]
            if head.isdigit() and not text.startswith("<"):  # octet-counted framing
                text = text[len(head) + 1:]
            buffer.add(text)


class ThreadingUDP(socketserver.ThreadingMixIn, socketserver.UDPServer):
    allow_reuse_address = True


class ThreadingTCP(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_syslog() -> None:
    for server in (ThreadingUDP(("0.0.0.0", SYSLOG_PORT), UDPHandler),
                   ThreadingTCP(("0.0.0.0", SYSLOG_PORT), TCPHandler)):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=buffer.flush_forever, daemon=True).start()
    log.info("syslog listening on %s/udp and %s/tcp", SYSLOG_PORT, SYSLOG_PORT)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    db.open_pool()
    try:
        start_syslog()
    except OSError as exc:
        log.warning("syslog listener not started: %s", exc)
    log.info("collector %s up; connectors: %s", socket.gethostname(), ", ".join(sorted(KINDS)))
    with ThreadPoolExecutor(MAX_PARALLEL) as pool:
        while True:
            try:
                test_sources()
                for row in due():
                    pool.submit(poll, row)
            except Exception:
                log.exception("collector loop error")
            time.sleep(1)


if __name__ == "__main__":
    main()
