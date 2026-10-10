"""Each service's current health compared with its own recent baseline."""

from . import db

PULL_KINDS = {"prometheus", "loki", "grafana", "alertmanager", "elasticsearch", "opensearch",
              "datadog", "newrelic", "cloudwatch", "gcp_logging", "azure_monitor", "sentry",
              "splunk", "http_check"}
RECENT_SECONDS = 30
BASELINE_MINUTES = 15
BASELINE_GAP_SECONDS = 60


def snapshot(window_seconds: int = RECENT_SECONDS, service: str | None = None) -> list[dict]:
    rows = db.query(
        """
        WITH recent AS (
            SELECT service, sum(count) AS count, sum(errors) AS errors,
                   sum(p95_ms * count) / nullif(sum(count), 0) AS p95_ms,
                   max(ts) AS last_seen
            FROM metric_points WHERE ts > now() - make_interval(secs => %s)
            GROUP BY service
        ),
        baseline AS (
            -- Medians, so earlier incidents inside the window don't inflate the baseline.
            SELECT service, sum(count) AS count,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY errors::float / count)
                       FILTER (WHERE count > 0) AS error_rate,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY p95_ms)
                       FILTER (WHERE count > 0) AS p95_ms
            FROM metric_points
            WHERE ts BETWEEN now() - make_interval(mins => %s)
                         AND now() - make_interval(secs => %s)
            GROUP BY service
        )
        SELECT s.name AS service, s.current_sha AS sha,
               coalesce(r.count, 0) AS count, coalesce(r.errors, 0) AS errors,
               r.p95_ms, r.last_seen,
               coalesce(b.count, 0) AS baseline_count, b.error_rate AS baseline_error_rate,
               b.p95_ms AS baseline_p95_ms,
               (SELECT max(ts) FROM metric_points m WHERE m.service = s.name) AS last_point,
               (SELECT source FROM metric_points m WHERE m.service = s.name
                ORDER BY ts DESC LIMIT 1) AS last_source
        FROM services s
        LEFT JOIN recent r ON r.service = s.name
        LEFT JOIN baseline b ON b.service = s.name
        WHERE %s::text IS NULL OR s.name = %s
        ORDER BY s.name
        """,
        window_seconds, BASELINE_MINUTES, BASELINE_GAP_SECONDS, service, service)
    alerts = active_alerts(service)
    # Pull sources that were switched off or removed: their services went quiet on purpose.
    disconnected = {f"{r['kind']}:{r['name']}" for r in db.query(
        "SELECT kind, name FROM sources WHERE mode = 'pull' AND NOT enabled")}
    live_pull = {f"{r['kind']}:{r['name']}" for r in db.query(
        "SELECT kind, name FROM sources WHERE mode = 'pull' AND enabled")}
    log_errors = log_error_rates(window_seconds, service)
    out = []
    for r in rows:
        rate = r["errors"] / r["count"] if r["count"] else 0.0
        base_rate = r["baseline_error_rate"]
        out.append({
            "service": r["service"],
            "sha": (r["sha"] or "")[:10],
            "requests": int(r["count"]),
            "error_rate": round(rate, 4),
            "p95_ms": round(r["p95_ms"], 1) if r["p95_ms"] is not None else None,
            "baseline_error_rate": round(base_rate, 4) if base_rate is not None else None,
            "baseline_p95_ms": round(r["baseline_p95_ms"], 1) if r["baseline_p95_ms"] else None,
            "baseline_requests": int(r["baseline_count"]),
            "last_seen": r["last_point"],
            "status": status_of(rate, r["count"], base_rate, r["p95_ms"], r["baseline_p95_ms"],
                                r["last_point"], r["last_seen"]),
        })
        src = r["last_source"]
        if out[-1]["status"] == "silent" and src and (
                src in disconnected or (src.split(":")[0] in PULL_KINDS and src not in live_pull)):
            out[-1]["status"] = "healthy"
        entry = out[-1]
        logs = log_errors.get(entry["service"])
        if logs:
            entry["error_logs"] = logs["recent"]
            entry["baseline_error_logs"] = logs["baseline"]
            # Services we only see through logs: judge them by their error-log rate.
            if (entry["status"] == "healthy" and not entry["requests"]
                    and not entry["baseline_requests"] and logs["known"]
                    and logs["recent"] >= max(5, logs["baseline"] * 3 + 3)):
                entry["status"] = "logging errors"
        if alerts.get(entry["service"]):
            entry["alerts"] = alerts[entry["service"]]
            if entry["status"] == "healthy" and any(a["severity"] in ("critical", "error")
                                                    and not a["handled"] for a in entry["alerts"]):
                entry["status"] = "alerting"
    return out


def active_alerts(service: str | None = None) -> dict[str, list[dict]]:
    """Firing alerts, crashes, restarts and failed checks reported by connected sources."""
    out: dict[str, list[dict]] = {}
    for e in db.query(
            "SELECT e.service, e.source, e.kind, e.severity, e.title, e.started_at, e.incident_id,"
            "       coalesce(i.status IN ('resolved', 'escalated'), false) AS handled"
            " FROM source_events e LEFT JOIN incidents i ON i.id = e.incident_id"
            " WHERE e.status = 'firing' AND e.active_until > now()"
            " AND (%s::text IS NULL OR e.service = %s) ORDER BY e.started_at DESC", service, service):
        out.setdefault(e["service"], []).append(e)
    return out


def log_error_rates(window_seconds: int, service: str | None = None) -> dict[str, dict]:
    rows = db.query(
        """
        SELECT service,
               coalesce(sum(count) FILTER (WHERE ts > now() - make_interval(secs => %s)), 0) AS recent,
               coalesce(sum(count) FILTER (WHERE ts <= now() - make_interval(secs => %s)), 0) AS base,
               min(ts) < now() - make_interval(mins => 3) AS known
        FROM log_events
        WHERE level IN ('error', 'critical') AND ts > now() - make_interval(mins => %s)
          AND (%s::text IS NULL OR service = %s)
        GROUP BY service
        """, window_seconds, BASELINE_GAP_SECONDS, BASELINE_MINUTES, service, service)
    windows = (BASELINE_MINUTES * 60 - BASELINE_GAP_SECONDS) / window_seconds
    known = {r["name"] for r in db.query(
        "SELECT name FROM services WHERE first_seen < now() - interval '3 minutes'")}
    return {r["service"]: {"recent": int(r["recent"]),
                           "baseline": round(float(r["base"]) / windows, 1),
                           "known": r["service"] in known}
            for r in rows}


def status_of(rate, count, base_rate, p95, base_p95, last_point, last_recent) -> str:
    if last_point is not None and last_recent is None:
        return "silent"
    if count >= 5 and rate >= 0.10 and rate > (base_rate or 0) * 3 + 0.05:
        return "erroring"
    if count >= 5 and p95 and base_p95 and p95 > max(base_p95 * 3, base_p95 + 300):
        return "slow"
    return "healthy"
