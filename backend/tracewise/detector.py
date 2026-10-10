"""Opens one incident per problem: unhealthy services that are connected are grouped together."""

from . import db, health

ACTIVE = ("open", "investigating", "acting", "fixing", "verifying")
RESOLVED_GRACE_SECONDS = 20  # verify_recovery already required 30s healthy
ESCALATED_QUIET_MINUTES = 30  # a human has it; don't reopen the same problem every minute
MIN_BASELINE_REQUESTS = 30    # one stray data point isn't a baseline


def neighbours() -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {}
    for e in db.query("SELECT src, dst FROM service_edges"):
        adj.setdefault(e["src"], set()).add(e["dst"])
        adj.setdefault(e["dst"], set()).add(e["src"])
    return adj


def components(services: list[str], adj: dict[str, set[str]]) -> list[set[str]]:
    left, groups = set(services), []
    while left:
        stack, group = [left.pop()], set()
        while stack:
            s = stack.pop()
            group.add(s)
            for n in adj.get(s, ()):
                if n in left:
                    left.remove(n)
                    stack.append(n)
        groups.append(group)
    return groups


def tick() -> None:
    snap = {s["service"]: s for s in health.snapshot()}
    unhealthy = [name for name, s in snap.items()
                 if s["status"] != "healthy"
                 and (s["baseline_requests"] >= MIN_BASELINE_REQUESTS
                      or s["status"] in ("alerting", "logging errors"))]
    if not unhealthy:
        return
    recently_resolved = {
        svc for row in db.query(
            "SELECT services FROM incidents WHERE (status = 'resolved'"
            " AND resolved_at > now() - make_interval(secs => %s)) OR (status = 'escalated'"
            " AND coalesce(resolved_at, opened_at) > now() - make_interval(mins => %s))",
            RESOLVED_GRACE_SECONDS, ESCALATED_QUIET_MINUTES)
        for svc in row["services"]
        # A new alert is new information even right after a human took over.
        if snap.get(svc, {}).get("status") != "alerting"}
    unhealthy = [s for s in unhealthy if s not in recently_resolved]
    if not unhealthy:
        return

    adj = neighbours()
    active = db.query("SELECT id, services FROM incidents WHERE status = ANY(%s) ORDER BY id",
                      list(ACTIVE))
    for group in components(unhealthy, adj):
        touching = group | {n for s in group for n in adj.get(s, ())}
        incident = next((i for i in active if touching & set(i["services"])), None)
        signals = [signal(snap[s]) for s in sorted(group)]
        claim_alerts(incident["id"] if incident else None, group)
        if incident:
            new = sorted(group - set(incident["services"]))
            if new:
                db.query("UPDATE incidents SET services = services || %s::text[],"
                         " signals = signals || %s WHERE id = %s",
                         new, db.jsonb([signal(snap[s]) for s in new]), incident["id"])
                db.add_step(incident["id"], "detector", f"Also affected: {', '.join(new)}",
                            {"signals": [signal(snap[s]) for s in new]})
            continue
        title = describe(group, snap)
        scenario = db.one("SELECT id, name FROM scenario_runs WHERE ended_at IS NULL"
                          " AND incident_id IS NULL AND started_at > now() - interval '15 minutes'"
                          " ORDER BY id DESC LIMIT 1")
        row = db.one(
            "INSERT INTO incidents (title, services, signals, severity, scenario)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id", title, sorted(group), db.jsonb(signals),
            "critical" if "gateway" in group else "high", scenario["name"] if scenario else None)
        if scenario:
            db.query("UPDATE scenario_runs SET incident_id = %s WHERE id = %s", row["id"],
                     scenario["id"])
        claim_alerts(row["id"], group)
        db.add_step(row["id"], "detector", title, {"signals": signals})
        db.notify("incident_events", {"type": "incident_opened", "incident_id": row["id"]})
        active.append({"id": row["id"], "services": sorted(group)})


def claim_alerts(incident_id: int | None, services: set[str]) -> None:
    """Link the alerts behind an incident to it, so they can't open another one later."""
    if incident_id:
        db.query("UPDATE source_events SET incident_id = %s WHERE service = ANY(%s)"
                 " AND status = 'firing' AND active_until > now() AND incident_id IS NULL",
                 incident_id, sorted(services))


def signal(s: dict) -> dict:
    out = {k: s[k] for k in ("service", "status", "error_rate", "baseline_error_rate", "p95_ms",
                             "baseline_p95_ms", "requests", "sha")}
    if s.get("alerts"):
        out["alerts"] = [{k: a[k] for k in ("source", "kind", "severity", "title")}
                         for a in s["alerts"][:5]]
    if s.get("error_logs"):
        out["error_logs"] = s["error_logs"]
        out["baseline_error_logs"] = s.get("baseline_error_logs")
    return out


def describe(group: set[str], snap: dict) -> str:
    parts = []
    for name in sorted(group):
        s = snap[name]
        if s["status"] == "erroring":
            parts.append(f"{name} failing {s['error_rate']:.0%} of requests")
        elif s["status"] == "slow":
            parts.append(f"{name} slow (p95 {s['p95_ms']:.0f} ms)")
        elif s["status"] == "alerting":
            parts.append(f"{name}: {s['alerts'][0]['title']}")
        elif s["status"] == "logging errors":
            parts.append(f"{name} logging {s['error_logs']} errors in 30s")
        else:
            parts.append(f"{name} stopped reporting")
    return "; ".join(parts)
