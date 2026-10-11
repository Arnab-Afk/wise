"""Push endpoints: everything that can send telemetry to Tracewise.

Each speaks the protocol the sending tool already uses, so connecting is a URL change:
- OpenTelemetry (OTLP/HTTP, JSON or protobuf): /otlp/v1/{logs,traces,metrics}
- Loki push API (Promtail, Grafana Alloy, Vector, Fluent Bit, Docker Loki driver): /loki/api/v1/push
- Elasticsearch bulk API (Fluent Bit, Logstash, Fluentd, Vector): /es/_bulk
- Splunk HTTP Event Collector: /splunk/services/collector
- Datadog log intake (Vector, Fluent Bit, Datadog libraries): /datadog/api/v2/logs
- Plain JSON / NDJSON (Vector, Fluent Bit, Fluentd, rsyslog, Vercel/Netlify drains, scripts): /v1/ingest/logs
- Heroku log drains (logplex): /v1/ingest/logplex
- AWS Kinesis Firehose HTTP endpoint (CloudWatch Logs subscriptions): /v1/ingest/firehose
- Alert webhooks: /v1/ingest/alerts/{alertmanager,grafana,datadog,pagerduty,opsgenie,sentry,
  cloudwatch,newrelic,azure,gcp,generic}
- Deploy webhooks: /v1/ingest/deploys/{github,gitlab,vercel,argocd,generic}
- The Tracewise host agent (pm2, systemd, Docker, Kubernetes, files, syslog): /v1/ingest/{logs,
  metrics,events,heartbeat}

Every endpoint takes the ingest key in whichever way the sender can provide it: the
x-ingest-key header, `Authorization: Bearer|Splunk|ApiKey <key>`, basic auth (key as password),
DD-API-KEY, X-Amz-Firehose-Access-Key, or ?key= in the URL.
"""

import base64
import gzip
import json
import time
import zlib

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import config, tenancy
from . import alerts, otlp, protowire, syslog
from .model import log_from_dict, register, service_name, store

router = APIRouter()

AGENTS = (("fluent-bit", "fluent-bit"), ("fluentd", "fluentd"), ("vector", "vector"),
          ("promtail", "promtail"), ("alloy", "alloy"), ("grafana-agent", "grafana-agent"),
          ("logstash", "logstash"), ("filebeat", "filebeat"), ("opentelemetry", "otel-collector"),
          ("otel", "otel"), ("alertmanager", "alertmanager"), ("grafana", "grafana"),
          ("datadog", "datadog"), ("amazon simple notification", "aws-sns"),
          ("firehose", "aws-firehose"), ("sentry", "sentry"), ("pagerduty", "pagerduty"),
          ("tracewise-agent", "tracewise-agent"), ("github-hookshot", "github"),
          ("gitlab", "gitlab"), ("vercel", "vercel"), ("logplex", "heroku"), ("rsyslog", "rsyslog"),
          ("newrelic", "newrelic"), ("azure", "azure"), ("google", "gcp"), ("uptime-kuma", "uptime-kuma"))


def ingest_key(request: Request) -> str | None:
    h = request.headers
    for name in ("x-ingest-key", "dd-api-key", "x-amz-firehose-access-key", "x-api-key"):
        if h.get(name):
            return h[name]
    auth = h.get("authorization", "")
    if " " in auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "basic":
            try:
                return base64.b64decode(value).decode().split(":", 1)[-1]
            except Exception:
                return None
        return value.strip()
    return request.query_params.get("key") or request.query_params.get("api_key")


def check(request: Request, key: str | None = None) -> dict:
    """The project this request's ingest key sends to; 401 without a valid key."""
    project = tenancy.project_for_key(key or ingest_key(request))
    if not project:
        raise HTTPException(401, "invalid ingest key")
    request.state.project = project
    return project


def source_name(request: Request, kind: str) -> str:
    explicit = request.query_params.get("source") or request.headers.get("x-tracewise-source")
    if explicit:
        return explicit
    ua = request.headers.get("user-agent", "").lower()
    return next((name for needle, name in AGENTS if needle in ua), kind)


async def raw_body(request: Request) -> bytes:
    body = await request.body()
    enc = (request.headers.get("content-encoding") or "").lower()
    ctype = (request.headers.get("content-type") or "").lower()
    try:
        if enc in ("gzip", "x-gzip") or body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        elif enc == "deflate":
            body = zlib.decompress(body)
        elif enc in ("snappy",) or "x-protobuf" in ctype and request.url.path.startswith("/loki"):
            import cramjam
            body = bytes(cramjam.snappy.decompress_raw(body))
        elif enc == "zstd":
            import cramjam
            body = bytes(cramjam.zstd.decompress(body))
    except Exception as exc:
        raise HTTPException(400, f"couldn't decompress body ({enc or 'auto'}): {exc}")
    return body


def parse_json_records(body: bytes) -> list:
    """A JSON array, a single object, an object wrapping a list, or NDJSON."""
    text = body.decode("utf-8", "replace").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"message": line})
        return out
    if isinstance(data, dict):
        for key in ("logs", "records", "events", "entries", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return data if isinstance(data, list) else [{"message": str(data)}]


def save(request: Request, kind: str, **records) -> dict:
    if "tracewise-agent" in request.headers.get("user-agent", ""):
        kind = "agent"  # the host agent's row in the sources list, named after the host
    name = source_name(request, kind)
    project_id = request.state.project["id"]
    source_id = register(kind, name, project_id)
    return store(f"{kind}:{name}" if name != kind else kind, project_id, source_id=source_id, **records)


async def asave(request: Request, kind: str, **records) -> dict:
    """Storage is blocking (psycopg); keep it off the event loop."""
    return await run_in_threadpool(save, request, kind, **records)


def forced_service(request: Request) -> str | None:
    return request.query_params.get("service") or request.headers.get("x-tracewise-service")


# ---------- generic / host agent ----------

@router.post("/v1/ingest/logs")
async def ingest_logs(request: Request):
    check(request)
    records = parse_json_records(await raw_body(request))
    service = forced_service(request)
    logs = []
    for r in records:
        if isinstance(r, str):
            r = {"message": r}
        if not isinstance(r, dict):
            continue
        # Fluent Bit / Fluentd wrap records as [timestamp, record]; Vercel uses "source" for stream.
        logs.append(log_from_dict(r, service))
    min_level = request.query_params.get("min_level")
    if min_level:
        from .model import RANK
        logs = [l for l in logs if RANK[l["level"]] >= RANK.get(min_level, 0)]
    return await asave(request, "http", logs=logs)


@router.post("/v1/ingest/metrics")
async def ingest_metrics(request: Request):
    check(request)
    records = parse_json_records(await raw_body(request))
    metrics = [{"service": r.get("service") or forced_service(request) or "unknown",
                "ts": r.get("ts") or r.get("timestamp"),
                "count": r.get("count", r.get("requests", 0)), "errors": r.get("errors", 0),
                "p50_ms": r.get("p50_ms", 0), "p95_ms": r.get("p95_ms", 0),
                "max_ms": r.get("max_ms", r.get("p95_ms", 0)), "sha": r.get("sha")}
               for r in records if isinstance(r, dict)]
    return await asave(request, "http", metrics=metrics)


@router.post("/v1/ingest/events")
async def ingest_events(request: Request):
    check(request)
    records = parse_json_records(await raw_body(request))
    return await asave(request, "http", events=[r for r in records if isinstance(r, dict)])


@router.post("/v1/ingest/heartbeat")
async def heartbeat(request: Request):
    """The host agent says it's alive and what it's watching."""
    project = check(request)
    body = json.loads(await raw_body(request) or b"{}")
    from .. import db
    db.query("INSERT INTO sources (project_id, kind, name, mode, status, config, last_received_at)"
             " VALUES (%s, 'agent', %s, 'push', 'receiving', %s, now())"
             " ON CONFLICT (project_id, kind, name) DO UPDATE SET config = EXCLUDED.config,"
             " status = 'receiving', last_received_at = now()",
             project["id"], body.get("host", "unknown"), db.jsonb(body))
    return {"ok": True}


# ---------- OpenTelemetry ----------

async def _otlp(request: Request, signal: str) -> dict:
    body = await raw_body(request)
    ctype = request.headers.get("content-type", "")
    payload = otlp.decode_protobuf(signal, body) if "protobuf" in ctype else json.loads(body or b"{}")
    if signal == "logs":
        await asave(request, "otlp", logs=otlp.logs(payload))
    elif signal == "traces":
        metrics, edges, logs = otlp.traces(payload)
        await asave(request, "otlp", metrics=metrics, edges=edges, logs=logs)
    else:
        await asave(request, "otlp", metrics=otlp.metrics(payload))
    return {}


def _otlp_response(request: Request, result: dict) -> Response:
    if "protobuf" in request.headers.get("content-type", ""):
        return Response(b"", media_type="application/x-protobuf")
    return JSONResponse(result)


@router.post("/otlp/v1/logs")
async def otlp_logs(request: Request):
    check(request)
    return _otlp_response(request, await _otlp(request, "logs"))


@router.post("/otlp/v1/traces")
async def otlp_traces(request: Request):
    check(request)
    return _otlp_response(request, await _otlp(request, "traces"))


@router.post("/otlp/v1/metrics")
async def otlp_metrics(request: Request):
    check(request)
    return _otlp_response(request, await _otlp(request, "metrics"))


# ---------- Loki push ----------

def _labels(text: str) -> dict:
    import re
    return dict(re.findall(r'([a-zA-Z_][\w.]*)\s*=\s*"((?:[^"\\]|\\.)*)"', text or ""))


LOKI_SERVICE_LABELS = ("service_name", "service", "app", "application", "job", "container",
                       "container_name", "compose_service", "unit", "systemd_unit", "pod", "host")


@router.post("/loki/api/v1/push")
async def loki_push(request: Request):
    check(request)
    body = await raw_body(request)
    if "protobuf" in request.headers.get("content-type", ""):
        streams = [{"stream": _labels(s["labels"]),
                    "values": [[str(ns), line, meta] for ns, line, meta in s["entries"]]}
                   for s in protowire.loki_push(body)]
    else:
        streams = json.loads(body or b"{}").get("streams", [])
    service = forced_service(request)
    logs = []
    for s in streams:
        labels = s.get("stream") or s.get("labels") or {}
        if isinstance(labels, str):
            labels = _labels(labels)
        svc = service or alerts.service_from_labels(
            {k: labels[k] for k in LOKI_SERVICE_LABELS if labels.get(k)}, "unknown")
        if svc.endswith(".service"):
            svc = svc[:-8]
        for v in s.get("values") or s.get("entries") or []:
            if isinstance(v, dict):  # legacy {"ts": ..., "line": ...}
                ts, line, meta = v.get("ts"), v.get("line", ""), {}
            else:
                ts, line, meta = v[0], v[1], (v[2] if len(v) > 2 else {}) or {}
            try:
                rec = json.loads(line) if line.startswith("{") else None
            except json.JSONDecodeError:
                rec = None
            rec = rec if isinstance(rec, dict) else {"message": line}
            if labels.get("level") or labels.get("detected_level") or meta.get("level"):
                rec.setdefault("level", labels.get("level") or labels.get("detected_level") or meta.get("level"))
            log = log_from_dict(rec, svc)
            log["ts"] = log["ts"] or ts
            log["fields"] = {**{k: v for k, v in labels.items() if k not in ("level",)}, **log["fields"]}
            logs.append(log)
    await asave(request, "loki", logs=logs)
    return Response(status_code=204)


# ---------- Elasticsearch bulk ----------

ES_INFO = {"name": "tracewise", "cluster_name": "tracewise", "cluster_uuid": "tracewise",
           "version": {"number": "8.11.0", "build_flavor": "default", "lucene_version": "9.8.0",
                       "minimum_wire_compatibility_version": "7.17.0",
                       "minimum_index_compatibility_version": "7.0.0"},
           "tagline": "You Know, for Search"}


@router.get("/es")
@router.get("/es/")
@router.head("/es")
@router.head("/es/")
def es_info():
    return JSONResponse(ES_INFO, headers={"X-elastic-product": "Elasticsearch"})


@router.get("/es/_license")
def es_license():
    return JSONResponse({"license": {"status": "active", "type": "basic", "uid": "tracewise"}},
                        headers={"X-elastic-product": "Elasticsearch"})


@router.put("/es/{rest:path}")
@router.get("/es/_index_template/{rest:path}")
@router.get("/es/_ilm/{rest:path}")
@router.get("/es/_nodes/{rest:path}")
def es_noop(rest: str = ""):
    return JSONResponse({"acknowledged": True}, headers={"X-elastic-product": "Elasticsearch"})


@router.post("/es/_bulk")
@router.post("/es/{index}/_bulk")
async def es_bulk(request: Request, index: str | None = None):
    check(request)
    started = time.time()
    lines = (await raw_body(request)).decode("utf-8", "replace").splitlines()
    service, logs, items, i = forced_service(request), [], [], 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        try:
            action = json.loads(lines[i])
            op = next(iter(action))
            if op == "delete":
                i += 1
                continue
            doc = json.loads(lines[i + 1]) if i + 1 < len(lines) else {}
        except (json.JSONDecodeError, StopIteration):
            raise HTTPException(400, f"line {i + 1} of the bulk body isn't valid NDJSON")
        i += 2
        if op == "update":
            doc = doc.get("doc") or {}
        logs.append(log_from_dict(doc, service))
        items.append({op: {"_index": action[op].get("_index") or index or "logs", "status": 201,
                           "result": "created", "_id": str(len(items))}})
    await asave(request, "elasticsearch", logs=logs)
    return JSONResponse({"took": int((time.time() - started) * 1000), "errors": False, "items": items},
                        headers={"X-elastic-product": "Elasticsearch"})


# ---------- Splunk HEC ----------

@router.get("/splunk/services/collector/health")
@router.get("/splunk/services/collector/health/1.0")
def hec_health():
    return {"text": "HEC is healthy", "code": 17}


@router.post("/splunk/services/collector")
@router.post("/splunk/services/collector/event")
@router.post("/splunk/services/collector/event/1.0")
async def hec_event(request: Request):
    check(request)
    text = (await raw_body(request)).decode("utf-8", "replace")
    decoder, i, logs = json.JSONDecoder(), 0, []
    while i < len(text):  # HEC batches are concatenated JSON objects, not an array
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        obj, i = decoder.raw_decode(text, i)
        event = obj.get("event")
        rec = event if isinstance(event, dict) else {"message": str(event)}
        rec = {**(obj.get("fields") or {}), **rec}
        log = log_from_dict(rec, forced_service(request) or rec.get("service")
                            or obj.get("source") or obj.get("sourcetype") or obj.get("host"))
        log["ts"] = log["ts"] or obj.get("time")
        logs.append(log)
    await asave(request, "splunk-hec", logs=logs)
    return {"text": "Success", "code": 0}


@router.post("/splunk/services/collector/raw")
@router.post("/splunk/services/collector/raw/1.0")
async def hec_raw(request: Request):
    check(request)
    service = forced_service(request) or request.query_params.get("sourcetype") or "splunk"
    lines = (await raw_body(request)).decode("utf-8", "replace").splitlines()
    await asave(request, "splunk-hec", logs=[log_from_dict({"message": l}, service) for l in lines if l.strip()])
    return {"text": "Success", "code": 0}


# ---------- Datadog log intake ----------

@router.post("/datadog/api/v2/logs")
@router.post("/datadog/v1/input")
@router.post("/datadog/v1/input/{key}")
async def datadog_logs(request: Request, key: str | None = None):
    check(request, key)
    logs = []
    for r in parse_json_records(await raw_body(request)):
        if not isinstance(r, dict):
            continue
        tags = alerts.tags_to_dict(r.get("ddtags"))
        rec = {**r, "level": r.get("status") or r.get("level")}
        logs.append(log_from_dict(rec, forced_service(request) or r.get("service")
                                  or tags.get("service") or r.get("ddsource") or r.get("hostname")))
    await asave(request, "datadog-intake", logs=logs)
    return JSONResponse({}, status_code=202)


# ---------- Heroku / syslog-over-HTTP ----------

@router.post("/v1/ingest/logplex")
async def logplex(request: Request):
    check(request)
    text = (await raw_body(request)).decode("utf-8", "replace")
    await asave(request, "logplex", logs=syslog.logplex(text, forced_service(request)))
    return Response(status_code=204)


# ---------- AWS Kinesis Firehose (CloudWatch Logs subscription) ----------

@router.post("/v1/ingest/firehose")
async def firehose(request: Request):
    body = json.loads(await raw_body(request) or b"{}")
    request_id = body.get("requestId") or request.headers.get("x-amz-firehose-request-id", "")
    reply = lambda status, msg=None: JSONResponse(  # noqa: E731
        {"requestId": request_id, "timestamp": int(time.time() * 1000),
         **({"errorMessage": msg} if msg else {})}, status_code=status)
    try:
        check(request)
    except HTTPException:
        return reply(401, "invalid access key")
    logs = []
    for rec in body.get("records", []):
        data = base64.b64decode(rec.get("data", ""))
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        for chunk in data.decode("utf-8", "replace").splitlines() or [""]:
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                obj = {"message": chunk}
            if obj.get("messageType") == "CONTROL_MESSAGE":
                continue
            if "logEvents" in obj:  # a CloudWatch Logs subscription batch
                group = obj.get("logGroup", "")
                svc = forced_service(request) or cloudwatch_service(group, obj.get("logStream", ""))
                for ev in obj["logEvents"]:
                    msg = ev.get("message", "")
                    try:
                        inner = json.loads(msg) if msg.startswith("{") else {"message": msg}
                    except json.JSONDecodeError:
                        inner = {"message": msg}
                    log = log_from_dict(inner, svc)
                    log["ts"] = log["ts"] or ev.get("timestamp")
                    log["fields"].update({"log_group": group, "log_stream": obj.get("logStream")})
                    logs.append(log)
            else:
                logs.append(log_from_dict(obj, forced_service(request)))
    await asave(request, "firehose", logs=logs)
    return reply(200)


def cloudwatch_service(group: str, stream: str = "") -> str:
    """/aws/lambda/checkout -> checkout, /ecs/payments -> payments, /aws/eks/x/cluster -> x."""
    parts = [p for p in group.split("/") if p and p not in ("aws", "ecs", "lambda", "containerinsights",
                                                             "apigateway", "eks", "rds", "instance")]
    return parts[0] if parts else (stream.split("/")[0] or "cloudwatch")


# ---------- alert and deploy webhooks ----------

async def _json_or_text(request: Request):
    body = await raw_body(request)
    try:
        return json.loads(body or b"{}")
    except json.JSONDecodeError:
        return {"message": body.decode("utf-8", "replace")}


@router.post("/v1/ingest/alerts/{kind}")
async def alert_webhook(kind: str, request: Request):
    check(request)
    parser = alerts.ALERT_PARSERS.get(kind)
    if not parser:
        raise HTTPException(404, f"unknown alert source {kind}; try one of {sorted(alerts.ALERT_PARSERS)}")
    body = await _json_or_text(request)
    if kind in ("cloudwatch", "sns"):
        sns_type = request.headers.get("x-amz-sns-message-type") or body.get("Type")
        if sns_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation", "Notification"):
            verify_sns(body)
        if sns_type == "SubscriptionConfirmation":
            httpx.get(body["SubscribeURL"], timeout=10)
            return {"confirmed": True}
    events, logs, deploys = parser(body, forced_service(request))
    result = await asave(request, kind, events=events, logs=logs, deploys=deploys)
    return result


@router.post("/v1/ingest/deploys/{kind}")
async def deploy_webhook(kind: str, request: Request):
    check(request)
    parser = alerts.DEPLOY_PARSERS.get(kind)
    if not parser:
        raise HTTPException(404, f"unknown deploy source {kind}; try one of {sorted(alerts.DEPLOY_PARSERS)}")
    if request.headers.get("x-github-event") == "ping":
        return {"ok": True}
    events, logs, deploys = parser(await _json_or_text(request), forced_service(request))
    return await asave(request, kind, events=events, logs=logs, deploys=deploys)


# ---------- SNS signature verification ----------

_SNS_FIELDS = {
    "Notification": ("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"),
    "SubscriptionConfirmation": ("Message", "MessageId", "SubscribeURL", "Timestamp", "Token",
                                 "TopicArn", "Type"),
}
_SNS_FIELDS["UnsubscribeConfirmation"] = _SNS_FIELDS["SubscriptionConfirmation"]
_cert_cache: dict[str, object] = {}


def verify_sns(msg: dict) -> None:
    """Check an SNS message really came from AWS (signature over the canonical fields)."""
    from urllib.parse import urlparse

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    url = msg.get("SigningCertURL") or msg.get("SigningCertUrl") or ""
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or not (host.startswith("sns.") and host.endswith(".amazonaws.com")) \
            and not getattr(verify_sns, "trusted_cert_host", None) == host:
        raise HTTPException(400, "SNS signing certificate URL isn't an AWS SNS URL")
    if url not in _cert_cache:
        _cert_cache[url] = x509.load_pem_x509_certificate(httpx.get(url, timeout=10).content)
    canonical = "".join(f"{k}\n{msg[k]}\n" for k in _SNS_FIELDS[msg["Type"]] if k in msg)
    algo = hashes.SHA256() if str(msg.get("SignatureVersion")) == "2" else hashes.SHA1()
    try:
        _cert_cache[url].public_key().verify(base64.b64decode(msg["Signature"]), canonical.encode(),
                                             padding.PKCS1v15(), algo)
    except Exception:
        raise HTTPException(403, "SNS signature didn't verify")


__all__ = ["router", "service_name"]
