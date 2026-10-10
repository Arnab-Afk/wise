"""Connector tests against recorded/documented API shapes (no network, no database).

The live lab (integrations/lab) covers Prometheus, Loki, Grafana, Alertmanager, OpenSearch,
Promtail, Fluent Bit, Vector and the OpenTelemetry Collector against the real tools. These tests
cover the SaaS APIs we can't run locally, plus the parsers.
"""

import base64
import gzip
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tracewise.sources import alerts, otlp, protowire, syslog
from tracewise.sources.model import guess_level, level_of, log_from_dict, split_trace, to_ts
from tracewise.sources.pull import (AzureMonitor, Datadog, GCPLogging, HTTPCheck, NewRelic, Prometheus,
                                    Sentry, SourceError, Splunk)


def mock(routes):
    """routes: {(method, path-prefix): response-json or callable(request)}."""
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        for (method, prefix), resp in routes.items():
            if request.method == method and (request.url.path.startswith(prefix) or str(request.url).startswith(prefix)):
                if callable(resp):
                    resp = resp(request)
                if isinstance(resp, httpx.Response):
                    return resp
                return httpx.Response(200, json=resp)
        return httpx.Response(404, text=f"no route for {request.method} {request.url}")
    return httpx.MockTransport(handler), calls


# ---------------------------------------------------------------- normalisation

@pytest.mark.parametrize("value,expected", [
    ("ERROR", "error"), ("warn", "warning"), ("Sev1", "error"), ("Sev0", "critical"), (50, "error"),
    (60, "critical"), (3, "error"), (6, "info"), ("fatal", "critical"), ("notice", "info"), (None, "info"),
])
def test_levels(value, expected):
    assert level_of(value) == expected


def test_otel_severity_numbers():
    assert level_of(17, scheme="otel") == "error"
    assert level_of(9, scheme="otel") == "info"
    assert level_of(21, scheme="otel") == "critical"


@pytest.mark.parametrize("text,expected", [
    ("Error: R14 Memory quota exceeded", "error"), ("KeyError: 'sku'", "error"),
    ("0 errors found", "info"), ("2026/10/10 [error] 12#0: upstream timed out", "error"),
    ("level=warn msg=slow", "warning"), ("panic: runtime error", "critical"),
])
def test_guess_level(text, expected):
    assert guess_level(text) == expected


def test_timestamps():
    assert to_ts(1791650000).year == 2026
    assert to_ts(1791650000123).microsecond == 123000
    assert to_ts("1791650000000000000").year == 2026
    assert to_ts("2026-10-10T10:00:00.123456789Z").microsecond == 123456
    assert to_ts("10/Oct/2026:13:55:36 +0000").hour == 13
    future = datetime.now(timezone.utc) + timedelta(days=1)
    assert to_ts(future) <= datetime.now(timezone.utc) + timedelta(seconds=6)


def test_split_trace_python_and_node():
    py = 'Traceback (most recent call last):\n  File "a.py", line 3, in f\n    x()\nValueError: bad value'
    assert split_trace(py) == ("ValueError: bad value", py)
    node = "TypeError: x is undefined\n    at f (/app/a.js:3:9)\n    at g (/app/b.js:1:1)"
    assert split_trace(node)[0] == "TypeError: x is undefined"
    assert split_trace("one line") == ("one line", None)


def test_log_from_dict_ecs_and_nested():
    log = log_from_dict({"@timestamp": "2026-10-10T10:00:00Z", "service": {"name": "checkout"},
                         "log": {"level": "error"}, "message": "boom", "http": {"response": {"status_code": 502}},
                         "fields": {"host": "web1"}})
    assert (log["service"], log["level"], log["message"], log["fields"]["host"]) == ("checkout", "error", "boom", "web1")
    assert log_from_dict({"msg": {"a": 1}, "level": 50, "app": "x"})["message"] == '{"a": 1}'


# ---------------------------------------------------------------- alert webhooks

def test_alertmanager_webhook():
    events, _, _ = alerts.alertmanager({"alerts": [{
        "status": "firing", "labels": {"alertname": "HighErrorRate", "job": "checkout", "severity": "page"},
        "annotations": {"summary": "5xx > 10%"}, "startsAt": "2026-10-10T10:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z", "fingerprint": "f1"}]})
    e = events[0]
    assert (e["service"], e["severity"], e["status"], e["fingerprint"]) == ("checkout", "critical", "firing", "f1")
    assert e["title"] == "HighErrorRate: 5xx > 10%"


def test_datadog_default_payload_recovered():
    events, _, _ = alerts.datadog({"title": "[Recovered] p99 high", "tags": "service:checkout,env:prod", "id": "9"})
    assert events[0]["status"] == "resolved" and events[0]["service"] == "checkout"


def test_pagerduty_ignores_non_incident_events():
    assert alerts.pagerduty({"event": {"event_type": "service.updated"}}) == ([], [], [])


def test_sentry_issue_alert_with_stack():
    events, logs, _ = alerts.sentry({"action": "triggered", "data": {"event": {
        "title": "ZeroDivisionError: division by zero", "level": "error", "project": 4, "issue_id": "77",
        "exception": {"values": [{"type": "ZeroDivisionError", "value": "division by zero", "stacktrace": {
            "frames": [{"filename": "app.py", "lineno": 3, "function": "total"}]}}]}}}}, service="api")
    assert events[0]["fingerprint"] == "sentry:77"
    assert 'File "app.py", line 3, in total' in logs[0]["trace"]


def test_cloudwatch_alarm_via_sns():
    msg = {"AlarmName": "checkout-5xx", "NewStateValue": "ALARM", "NewStateReason": "Threshold crossed",
           "Trigger": {"Dimensions": [{"name": "TargetGroup", "value": "targetgroup/checkout/abc"}]}}
    events, _, _ = alerts.cloudwatch({"Type": "Notification", "Message": json.dumps(msg)})
    assert events[0]["service"] == "checkout" and events[0]["status"] == "firing"


def test_azure_and_gcp_and_newrelic():
    az, _, _ = alerts.azure({"data": {"essentials": {"alertRule": "cpu", "severity": "Sev1", "monitorCondition": "Resolved",
                                                     "configurationItems": ["vm-checkout"], "alertId": "a1"}}})
    assert (az[0]["status"], az[0]["service"], az[0]["severity"]) == ("resolved", "vm-checkout", "critical")
    gcp, _, _ = alerts.gcp({"incident": {"incident_id": "i1", "state": "open", "policy_name": "Latency",
                                         "resource": {"labels": {"service_name": "checkout"}}}})
    assert gcp[0]["service"] == "checkout" and gcp[0]["status"] == "firing"
    nr, _, _ = alerts.newrelic({"issueId": "n1", "title": "Error rate", "priority": "CRITICAL", "state": "CLOSED",
                                "impactedEntities": ["checkout-api"]})
    assert (nr[0]["status"], nr[0]["service"]) == ("resolved", "checkout-api")


def test_generic_status_words():
    for status, expected in (("broken", "firing"), ("ok", "resolved"), ("up", "resolved"), ("DOWN", "firing")):
        events, _, _ = alerts.generic({"service": "x", "title": "t", "status": status})
        assert events[0]["status"] == expected, status


def test_deploy_webhooks():
    _, _, d = alerts.deploy_github({"deployment_status": {"state": "success"}, "deployment": {
        "sha": "abc", "environment": "prod", "creator": {"login": "rahul"}}, "repository": {"name": "shop"}})
    assert (d[0]["service"], d[0]["sha"], d[0]["author"]) == ("shop", "abc", "rahul")
    _, _, v = alerts.deploy_vercel({"type": "deployment.succeeded", "payload": {
        "project": {"name": "web"}, "deployment": {"meta": {"githubCommitSha": "def"}}}})
    assert v[0]["sha"] == "def"


def test_sns_signature_verification(monkeypatch):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.x509.oid import NameOID
    from fastapi import HTTPException

    from tracewise.sources import receivers

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1)).sign(key, hashes.SHA256()))
    url = "https://sns.us-east-1.amazonaws.com/cert.pem"
    receivers._cert_cache[url] = x509.load_pem_x509_certificate(cert.public_bytes(serialization.Encoding.PEM))
    msg = {"Type": "Notification", "MessageId": "m1", "TopicArn": "arn:t", "Message": "{}",
           "Timestamp": "2026-10-10T10:00:00Z", "SignatureVersion": "2", "SigningCertURL": url}
    canonical = "".join(f"{k}\n{msg[k]}\n" for k in ("Message", "MessageId", "Timestamp", "TopicArn", "Type"))
    msg["Signature"] = base64.b64encode(key.sign(canonical.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
    receivers.verify_sns(msg)  # valid: no exception
    with pytest.raises(HTTPException):
        receivers.verify_sns({**msg, "Message": '{"tampered": true}'})
    with pytest.raises(HTTPException):
        receivers.verify_sns({**msg, "SigningCertURL": "https://evil.example.com/cert.pem"})


# ---------------------------------------------------------------- formats

def test_syslog_and_logplex():
    r = syslog.parse("<11>1 2026-10-10T10:00:00Z web1 billing 77 - - payment timeout")
    assert (r["service"], r["level"]) == ("billing", "error")
    r = syslog.parse("<30>Oct 10 10:00:00 web1 nginx[12]: ERROR upstream gone")
    assert (r["service"], r["level"]) == ("nginx", "error")
    frame = "<190>1 2026-10-10T10:00:00+00:00 host app web.1 - - Error: R14 Memory quota exceeded"
    out = syslog.logplex(f"{len(frame)} {frame}{len(frame)} {frame}", "shop")
    assert len(out) == 2 and out[0]["level"] == "error" and out[0]["service"] == "shop"


def test_loki_protobuf_decoder():
    def varint(n):
        out = b""
        while True:
            b = n & 0x7F
            n >>= 7
            out += bytes([b | (0x80 if n else 0)])
            if not n:
                return out

    def field(num, payload):
        return varint(num << 3 | 2) + varint(len(payload)) + payload
    ts = varint(1 << 3 | 0) + varint(1791650000) + varint(2 << 3 | 0) + varint(5)
    entry = field(1, ts) + field(2, b"boom")
    stream = field(1, b'{app="checkout"}') + field(2, entry)
    streams = protowire.loki_push(field(1, stream))
    assert streams == [{"labels": '{app="checkout"}', "entries": [(1791650000 * 10**9 + 5, "boom", {})]}]


def test_otlp_traces_metrics_and_cumulative_histograms():
    now = time.time_ns()
    payload = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "api"}}]},
               "scopeSpans": [{"spans": [
                   {"kind": "SPAN_KIND_SERVER", "startTimeUnixNano": str(now - 10**8), "endTimeUnixNano": str(now),
                    "attributes": [{"key": "http.response.status_code", "value": {"intValue": "503"}}]},
                   {"kind": 3, "startTimeUnixNano": str(now - 10**7), "endTimeUnixNano": str(now),
                    "attributes": [{"key": "server.address", "value": {"stringValue": "db.internal:5432"}}]}]}]}]}
    metrics, edges, _ = otlp.traces(payload)
    assert metrics[0]["errors"] == 1 and metrics[0]["p95_ms"] == 100.0
    assert edges[0]["dst"] == "db"

    def hist(count, buckets):
        return {"resourceMetrics": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "h"}}]},
                "scopeMetrics": [{"metrics": [{"name": "http.server.request.duration", "histogram": {
                    "aggregationTemporality": 2, "dataPoints": [{"count": str(count), "explicitBounds": [0.1, 0.5],
                                                                 "bucketCounts": [str(b) for b in buckets]}]}}]}]}]}
    assert otlp.metrics(hist(10, [10, 0, 0])) == []          # first sight of a cumulative series
    m = otlp.metrics(hist(30, [10, 20, 0]))[0]                # 20 new requests, all in 100-500 ms
    assert m["count"] == 20 and 100 <= m["p50_ms"] <= 500


# ---------------------------------------------------------------- pull connectors (mocked APIs)

def test_prometheus_poll_and_alert_resolution():
    def query(request):
        q = dict(httpx.QueryParams(request.content.decode()))["query"]
        if q.startswith("ALERTS"):
            return {"status": "success", "data": {"result": [] if query.resolved else [
                {"metric": {"alertname": "Down", "service": "api"}, "value": [0, "1"]}]}}
        value = "250" if "histogram_quantile" in q else "10"  # the query itself converts to ms
        if "5.." in q:
            value = "2"
        return {"status": "success", "data": {"result": [{"metric": {"service": "api"}, "value": [0, value]}]}}
    query.resolved = False
    transport, _ = mock({("POST", "/api/v1/query"): query})
    src = Prometheus({"url": "http://prom", "interval_seconds": 15}, transport=transport)
    records, state = src.poll({})
    m = records["metrics"][0]
    assert (m["count"], m["errors"], m["p95_ms"]) == (150, 30, 250.0)
    assert records["events"][0]["status"] == "firing"
    query.resolved = True
    records, _ = src.poll(state)
    assert records["events"][0]["status"] == "resolved"


def test_datadog_logs_metrics_and_monitors():
    transport, calls = mock({
        ("POST", "/api/v2/logs/events/search"): {"data": [{"id": "l1", "attributes": {
            "timestamp": "2026-10-10T10:00:00Z", "service": "checkout", "status": "error", "message": "boom",
            "attributes": {"error": {"stack": "Traceback..."}}}}]},
        ("GET", "/api/v1/query"): lambda r: {"series": [{"scope": "service:checkout",
                                                          "pointlist": [[0, 0.3 if "p95" in r.url.params["query"] else 100]]}]},
        ("GET", "/api/v1/monitor"): [{"id": 5, "name": "Checkout errors", "overall_state": "Alert",
                                      "tags": ["service:checkout"], "priority": 1}],
    })
    records, state = Datadog({"site": "datadoghq.eu", "api_key": "a", "app_key": "b"}, transport=transport).poll({})
    assert records["logs"][0]["trace"] == "Traceback..."
    assert records["metrics"][0]["p95_ms"] == 300.0
    assert records["events"][0]["title"] == "Checkout errors"
    assert calls[0].url.host == "api.datadoghq.eu" and calls[0].headers["DD-API-KEY"] == "a"


def test_newrelic_nrql():
    def graphql(request):
        q = json.loads(request.content)["variables"]["q"]
        rows = ([{"timestamp": 1791650000000, "message": "boom", "level": "error", "service.name": "api",
                  "error.stack": "at x"}] if "FROM Log" in q else
                [{"facet": "api", "requests": 100, "errors": 4, "percentile.duration": {"50": 0.02, "95": 0.4, "99": 1.0}}])
        return {"data": {"actor": {"account": {"nrql": {"results": rows}}}}}
    transport, calls = mock({("POST", "https://api.eu.newrelic.com/graphql"): graphql})
    records, state = NewRelic({"account_id": "1", "api_key": "k", "region": "eu"}, transport=transport).poll({})
    assert records["logs"][0]["service"] == "api" and records["metrics"][0]["p95_ms"] == 400.0
    assert state["cursor"] == 1791650000001 and calls[0].headers["API-Key"] == "k"


def test_gcp_logging_signs_a_jwt_and_reads_entries():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    transport, calls = mock({
        ("POST", "https://oauth2.googleapis.com/token"): {"access_token": "t"},
        ("POST", "/v2/entries:list"): {"entries": [{"insertId": "i1", "timestamp": "2026-10-10T10:00:00Z",
                                                    "severity": "ERROR", "jsonPayload": {"message": "boom"},
                                                    "resource": {"type": "cloud_run_revision",
                                                                 "labels": {"service_name": "checkout"}}}]},
    })
    sa = json.dumps({"client_email": "x@p.iam.gserviceaccount.com", "private_key": pem})
    records, state = GCPLogging({"project_id": "p"}, {"service_account_json": sa}, transport).poll({})
    assert records["logs"][0]["service"] == "checkout" and records["logs"][0]["level"] == "error"
    assert calls[1].headers["Authorization"] == "Bearer t"
    assert "assertion" in calls[0].content.decode()


def test_azure_kql():
    transport, _ = mock({
        ("POST", "https://login.microsoftonline.com/"): {"access_token": "t"},
        ("POST", "/v1/workspaces/w/query"): {"tables": [{"columns": [{"name": c} for c in
                                                                      ("TimeGenerated", "Service", "Level", "Message", "Trace")],
                                                         "rows": [["2026-10-10T10:00:00Z", "api", "error", "boom", ""]]}]},
    })
    records, _ = AzureMonitor({"tenant_id": "t", "client_id": "c", "workspace_id": "w"},
                              {"client_secret": "s"}, transport).poll({})
    assert records["logs"][0] == {"service": "api", "ts": "2026-10-10T10:00:00Z", "level": "error",
                                  "message": "boom", "trace": None, "fields": {}}


def test_sentry_counts_new_events_only():
    issue = {"id": "1", "title": "KeyError: sku", "level": "error", "count": "5", "project": {"slug": "api"},
             "lastSeen": datetime.now(timezone.utc).isoformat()}
    transport, _ = mock({("GET", "/api/0/organizations/o/issues/1/events/latest/"): {"exception": {"values": []}},
                         ("GET", "/api/0/organizations/o/issues/"): lambda r: [issue]})
    src = Sentry({"organization": "o"}, {"token": "t"}, transport)
    records, state = src.poll({})
    assert records["logs"][0]["count"] == 1
    issue["count"] = "9"
    records, state = src.poll(state)
    assert records["logs"][0]["count"] == 4
    records, _ = src.poll(state)
    assert records["logs"] == []


def test_splunk_export_ndjson():
    body = "\n".join(json.dumps({"result": r}) for r in (
        {"_time": "2026-10-10T10:00:00Z", "_raw": '{"level":"ERROR","message":"boom"}', "sourcetype": "checkout"},
        {"_time": "2026-10-10T10:00:01Z", "_raw": "plain ERROR line", "host": "web1"}))
    transport, _ = mock({("POST", "/services/search/jobs/export"): httpx.Response(200, text=body)})
    records, _ = Splunk({"url": "https://splunk:8089"}, {"token": "t"}, transport).poll({})
    assert [l["service"] for l in records["logs"]] == ["checkout", "web1"]


def test_errors_are_readable():
    transport, _ = mock({("POST", "/api/v1/query"): httpx.Response(401, text="unauthorized")})
    with pytest.raises(SourceError, match="credentials rejected"):
        Prometheus({"url": "http://prom"}, transport=transport).test()


def test_http_check_down_and_back():
    state_box = {"up": False}
    transport, _ = mock({("GET", "http://svc/healthz"): lambda r: httpx.Response(200 if state_box["up"] else 503)})
    src = HTTPCheck({"targets": "api http://svc/healthz"}, transport=transport)
    records, state = src.poll({})
    assert records["events"][0]["status"] == "firing" and records["metrics"][0]["errors"] == 2
    state_box["up"] = True
    records, _ = src.poll(state)
    assert records["events"][0]["status"] == "resolved"
