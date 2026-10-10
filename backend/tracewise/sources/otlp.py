"""OpenTelemetry (OTLP) logs, traces and metrics -> Tracewise logs, request metrics and edges.

Accepts OTLP/HTTP in JSON or protobuf (decoded into the same dict shape). From traces we get the
whole picture: server spans become request metrics, client spans become dependency edges, and
exception events become error logs with their stack traces.
"""

import json
import threading
from collections import defaultdict

from .model import level_of, split_trace

SERVER_KINDS = {2, 5, "SPAN_KIND_SERVER", "SPAN_KIND_CONSUMER"}
CLIENT_KINDS = {3, 4, "SPAN_KIND_CLIENT", "SPAN_KIND_PRODUCER"}


def decode_protobuf(signal: str, body: bytes) -> dict:
    from google.protobuf.json_format import MessageToDict
    if signal == "logs":
        from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest as M
    elif signal == "traces":
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest as M
    else:
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest as M
    msg = M()
    msg.ParseFromString(body)
    return MessageToDict(msg)


def value(v: dict | None):
    if not v:
        return None
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in v:
            return v[key]
    if "intValue" in v:
        return int(v["intValue"])
    if "arrayValue" in v:
        return [value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return attrs(v["kvlistValue"].get("values", []))
    return None


def attrs(items) -> dict:
    return {a["key"]: value(a.get("value")) for a in items or [] if "key" in a}


def service_of(resource: dict) -> tuple[str, str | None]:
    ra = attrs((resource or {}).get("attributes"))
    name = (ra.get("service.name") or ra.get("k8s.deployment.name") or ra.get("container.name")
            or ra.get("process.executable.name") or "unknown")
    if name.startswith("unknown_service") and ra.get("process.executable.name"):
        name = ra["process.executable.name"]
    return name, ra.get("service.version")


def nanos(x) -> int:
    return int(x or 0)


def host_service(addr: str | None) -> str | None:
    if not addr:
        return None
    host = str(addr).split("://")[-1].split("/")[0].split(":")[0]
    if not host or host.replace(".", "").isdigit():
        return host or None
    return host.split(".")[0]


# ---------- logs ----------

def logs(payload: dict) -> list[dict]:
    out = []
    for rl in payload.get("resourceLogs", []):
        service, version = service_of(rl.get("resource"))
        for sl in rl.get("scopeLogs", []) or rl.get("instrumentationLibraryLogs", []):
            for r in sl.get("logRecords", []):
                a = attrs(r.get("attributes"))
                body = value(r.get("body"))
                if isinstance(body, dict):
                    message = str(body.get("message") or body.get("msg") or json.dumps(body))
                else:
                    message = "" if body is None else str(body)
                trace = a.get("exception.stacktrace")
                if a.get("exception.type") and not message:
                    message = f"{a['exception.type']}: {a.get('exception.message', '')}"
                if not trace:
                    message, trace = split_trace(message)
                level = level_of(r.get("severityNumber"), message, scheme="otel") \
                    if r.get("severityNumber") else level_of(r.get("severityText"), message)
                if trace and level in ("debug", "info"):
                    level = "error"
                status = a.get("http.response.status_code") or a.get("http.status_code")
                out.append({
                    "service": service, "ts": nanos(r.get("timeUnixNano") or r.get("observedTimeUnixNano")) or None,
                    "level": level, "message": message, "trace": trace, "sha": version,
                    "route": a.get("http.route") or a.get("url.path"),
                    "status": int(status) if status else None,
                    "fields": {k: v for k, v in a.items()
                               if not k.startswith("exception.") and not isinstance(v, (dict, list))},
                })
    return out


# ---------- traces ----------

def percentiles(durations: list[float]) -> tuple[float, float, float]:
    d = sorted(durations)
    if not d:
        return 0.0, 0.0, 0.0
    pick = lambda p: d[min(len(d) - 1, int(len(d) * p))]  # noqa: E731
    return round(pick(0.5), 1), round(pick(0.95), 1), round(d[-1], 1)


def traces(payload: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (metrics, edges, logs)."""
    server = defaultdict(lambda: {"durations": [], "errors": 0, "ts": 0, "sha": None})
    edges = defaultdict(lambda: {"calls": 0, "errors": 0, "ms": 0.0, "ts": 0})
    out_logs = []
    for rs in payload.get("resourceSpans", []):
        service, version = service_of(rs.get("resource"))
        for ss in rs.get("scopeSpans", []) or rs.get("instrumentationLibrarySpans", []):
            for span in ss.get("spans", []):
                a = attrs(span.get("attributes"))
                start, end = nanos(span.get("startTimeUnixNano")), nanos(span.get("endTimeUnixNano"))
                ms = max(0.0, (end - start) / 1e6)
                status = a.get("http.response.status_code") or a.get("http.status_code")
                code = (span.get("status") or {}).get("code")
                failed = code in (2, "STATUS_CODE_ERROR") or (status and int(status) >= 500)
                kind = span.get("kind")
                if kind in SERVER_KINDS:
                    s = server[service]
                    s["durations"].append(ms)
                    s["errors"] += 1 if failed else 0
                    s["ts"] = max(s["ts"], end)
                    s["sha"] = version
                elif kind in CLIENT_KINDS:
                    dst = (a.get("peer.service") or host_service(a.get("server.address"))
                           or host_service(a.get("net.peer.name")) or host_service(a.get("url.full"))
                           or host_service(a.get("http.url")) or a.get("db.system")
                           or a.get("messaging.destination.name") or a.get("rpc.service"))
                    if dst and dst != service:
                        e = edges[(service, dst)]
                        e["calls"] += 1
                        e["errors"] += 1 if failed else 0
                        e["ms"] += ms
                        e["ts"] = max(e["ts"], end)
                for ev in span.get("events", []):
                    if ev.get("name") != "exception":
                        continue
                    ea = attrs(ev.get("attributes"))
                    out_logs.append({
                        "service": service, "ts": nanos(ev.get("timeUnixNano")) or end or None,
                        "level": "error",
                        "message": f"{ea.get('exception.type', 'Exception')}: {ea.get('exception.message', '')}",
                        "trace": ea.get("exception.stacktrace"), "sha": version,
                        "route": a.get("http.route") or span.get("name"),
                        "status": int(status) if status else None,
                        "fields": {"span": span.get("name"), "trace_id": span.get("traceId")},
                    })
    metrics = []
    for service, s in server.items():
        p50, p95, mx = percentiles(s["durations"])
        metrics.append({"service": service, "ts": s["ts"] or None, "count": len(s["durations"]),
                        "errors": s["errors"], "p50_ms": p50, "p95_ms": p95, "max_ms": mx,
                        "sha": s["sha"]})
    edge_list = [{"src": src, "dst": dst, "calls": e["calls"], "errors": e["errors"],
                  "avg_ms": e["ms"] / max(e["calls"], 1), "ts": e["ts"] or None}
                 for (src, dst), e in edges.items()]
    return metrics, edge_list, out_logs


# ---------- metrics ----------

DURATION_METRICS = {"http.server.request.duration": 1000.0,  # seconds -> ms
                    "http.server.duration": 1.0,             # older semconv, ms
                    "rpc.server.duration": 1.0}
_prev: dict = {}
_lock = threading.Lock()


def _delta(key, count: int, buckets: list[int], cumulative: bool):
    if not cumulative:
        return count, buckets
    with _lock:
        prev = _prev.get(key)
        _prev[key] = (count, buckets)
    if not prev or prev[0] > count or len(prev[1]) != len(buckets):  # first sight or reset
        return 0, [0] * len(buckets)
    return count - prev[0], [b - a for a, b in zip(prev[1], buckets)]


def quantile(bounds: list[float], counts: list[int], q: float) -> float:
    total = sum(counts)
    if not total:
        return 0.0
    target, seen = q * total, 0
    for i, c in enumerate(counts):
        if seen + c >= target and c:
            lo = bounds[i - 1] if i > 0 else 0.0
            hi = bounds[i] if i < len(bounds) else (bounds[-1] * 2 if bounds else lo)
            return lo + (hi - lo) * (target - seen) / c
        seen += c
    return bounds[-1] if bounds else 0.0


def metrics(payload: dict) -> list[dict]:
    agg = defaultdict(lambda: {"count": 0, "errors": 0, "bounds": None, "buckets": None, "ts": 0,
                               "scale": 1.0, "sha": None})
    for rm in payload.get("resourceMetrics", []):
        service, version = service_of(rm.get("resource"))
        for sm in rm.get("scopeMetrics", []) or rm.get("instrumentationLibraryMetrics", []):
            for m in sm.get("metrics", []):
                scale = DURATION_METRICS.get(m.get("name"))
                hist = m.get("histogram")
                if scale is None or not hist:
                    continue
                temporality = hist.get("aggregationTemporality")
                cumulative = temporality in (2, "AGGREGATION_TEMPORALITY_CUMULATIVE")
                for dp in hist.get("dataPoints", []):
                    a = attrs(dp.get("attributes"))
                    bounds = [float(b) * scale for b in dp.get("explicitBounds", [])]
                    count, buckets = _delta((service, m["name"], json.dumps(a, sort_keys=True)),
                                            int(dp.get("count", 0)),
                                            [int(b) for b in dp.get("bucketCounts", [])], cumulative)
                    if not count:
                        continue
                    s = agg[service]
                    s["count"] += count
                    status = a.get("http.response.status_code") or a.get("http.status_code")
                    if (status and int(status) >= 500) or a.get("error.type"):
                        s["errors"] += count
                    if s["bounds"] is None or s["bounds"] == bounds:
                        s["bounds"] = bounds
                        s["buckets"] = [x + y for x, y in zip(s["buckets"] or [0] * len(buckets), buckets)]
                    s["ts"] = max(s["ts"], nanos(dp.get("timeUnixNano")))
                    s["sha"] = version
    out = []
    for service, s in agg.items():
        b, c = s["bounds"] or [], s["buckets"] or []
        out.append({"service": service, "ts": s["ts"] or None, "count": s["count"],
                    "errors": s["errors"], "p50_ms": round(quantile(b, c, 0.5), 1),
                    "p95_ms": round(quantile(b, c, 0.95), 1), "max_ms": round(quantile(b, c, 0.99), 1),
                    "sha": s["sha"]})
    return out
