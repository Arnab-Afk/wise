import json
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import config

pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=10, open=False,
                      kwargs={"row_factory": dict_row, "autocommit": True})


def open_pool() -> None:
    pool.open(wait=True, timeout=60)
    with pool.connection() as conn:
        conn.execute((Path(__file__).parent / "schema.sql").read_text())


def query(sql: str, *params) -> list[dict]:
    with pool.connection() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else []


def one(sql: str, *params) -> dict | None:
    rows = query(sql, *params)
    return rows[0] if rows else None


def jsonb(value) -> Jsonb:
    return Jsonb(value)


def add_step(incident_id: int, kind: str, title: str, data: dict | None = None,
             phase: str | None = None) -> dict:
    """Record a timeline step and tell any listeners (the SSE stream) about it."""
    row = one(
        "INSERT INTO incident_steps (incident_id, kind, phase, title, data)"
        " VALUES (%s, %s, %s, %s, %s) RETURNING id, incident_id, ts, kind, phase, title",
        incident_id, kind, phase, title, Jsonb(data or {}))
    notify("incident_events", {"type": "step", "incident_id": incident_id, "step_id": row["id"]})
    return row


def notify(channel: str, payload: dict) -> None:
    with pool.connection() as conn:
        conn.execute("SELECT pg_notify(%s, %s)", (channel, json.dumps(payload, default=str)))


def many(sql: str, rows: list[tuple]) -> None:
    if not rows:
        return
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
