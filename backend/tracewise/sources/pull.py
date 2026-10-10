"""Pull connectors: Tracewise reads from the observability tools a team already runs.

Each connector can be tested (credentials and reachability), polled (new error logs, request
metrics, firing alerts since the last cursor) and queried live by the agent in that tool's own
query language (PromQL, LogQL, Lucene, NRQL, Logs Insights, KQL, SPL...).
"""

import base64
import json
import time
from datetime import datetime, timedelta, timezone

import httpx

from .alerts import service_from_labels, tags_to_dict
from .model import first, level_of, log_from_dict, severity_of, to_ts


class SourceError(Exception):
    pass


def F(name, label, type="text", required=False, default=None, help=None, options=None):
    return {"name": name, "label": label, "type": type, "required": required, "default": default,
            "help": help, "options": options}


AUTH_FIELDS = [
    F("bearer_token", "Bearer token", "secret"),
    F("username", "Username (basic auth)"),
    F("password", "Password (basic auth)", "secret"),
    F("verify_tls", "Verify TLS certificates", "bool", default=True),
]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source:
    kind = ""
    label = ""
    category = ""
    fields: list[dict] = []
    interval = 15
    query_language = ""
    query_example = ""

    def __init__(self, config: dict, secrets: dict | None = None, transport=None):
        self.config = {f["name"]: f["default"] for f in self.fields if f["default"] is not None}
        self.config.update({k: v for k, v in (config or {}).items() if v not in (None, "")})
        self.secrets = secrets or {}
        self.transport = transport

    def get(self, name, default=None):
        value = self.secrets.get(name) or self.config.get(name)
        return default if value in (None, "") else value

    def headers(self) -> dict:
        h = {"User-Agent": "tracewise-collector/1.0"}
        if self.get("bearer_token"):
            h["Authorization"] = f"Bearer {self.get('bearer_token')}"
        if self.get("tenant"):
            h["X-Scope-OrgID"] = self.get("tenant")
        return h

    def client(self, base_url: str | None = None, headers: dict | None = None,
               timeout: float = 20) -> httpx.Client:
        auth = None
        if self.get("username") and self.get("password"):
            auth = httpx.BasicAuth(self.get("username"), self.get("password"))
        return httpx.Client(base_url=(base_url or self.get("url", "")).rstrip("/"),
                            headers={**self.headers(), **(headers or {})}, auth=auth,
                            timeout=timeout, verify=bool(self.get("verify_tls", True)),
                            transport=self.transport, follow_redirects=True)

    def request(self, client: httpx.Client, method: str, path: str, **kw):
        try:
            resp = client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise SourceError(f"couldn't reach {client.base_url or path}: {type(exc).__name__}: {exc}")
        if resp.status_code in (401, 403):
            raise SourceError(f"{resp.status_code}: credentials rejected ({resp.text[:200]})")
        if resp.status_code >= 400:
            raise SourceError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError:  # NDJSON (Splunk export), plain text
            return resp.text

    # Overridden by connectors
    def test(self) -> str:
        raise NotImplementedError

    def poll(self, state: dict) -> tuple[dict, dict]:
        return {}, state

    def query(self, q: str, minutes: int = 15):
        raise SourceError(f"{self.label} doesn't support live queries")

    @classmethod
    def describe(cls) -> dict:
        return {"kind": cls.kind, "label": cls.label, "category": cls.category, "mode": "pull",
                "fields": cls.fields, "interval": cls.interval,
                "query_language": cls.query_language, "query_example": cls.query_example}


def resolve_missing(state: dict, firing: list[dict], key: str = "firing") -> list[dict]:
    """Alerts we saw firing last poll that are gone now have resolved."""
    now_fps = {e["fingerprint"] for e in firing}
    resolved = [{"fingerprint": fp, "service": svc, "status": "resolved", "kind": "alert",
                 "title": title, "severity": "info"}
                for fp, (svc, title) in (state.get(key) or {}).items() if fp not in now_fps]
    state[key] = {e["fingerprint"]: (e["service"], e["title"]) for e in firing}
    return resolved


def am_alerts(items: list[dict]) -> list[dict]:
    """Alertmanager API v2 alert objects (also Grafana's built-in Alertmanager)."""
    out = []
    for a in items:
        if (a.get("status") or {}).get("state", "active") != "active":
            continue
        labels, ann = a.get("labels") or {}, a.get("annotations") or {}
        title = ann.get("summary") or labels.get("alertname") or "alert"
        if labels.get("alertname") and labels["alertname"] not in title:
            title = f"{labels['alertname']}: {title}"
        out.append({"service": service_from_labels(labels), "kind": "alert", "status": "firing",
                    "severity": severity_of(labels.get("severity"), "error"), "title": title,
                    "ts": a.get("startsAt"), "fingerprint": a.get("fingerprint") or json.dumps(labels, sort_keys=True),
                    "active_until": utcnow() + timedelta(minutes=3),
                    "detail": {"labels": labels, "annotations": ann, "url": a.get("generatorURL")}})
    return out


# ---------------------------------------------------------------- Prometheus

PROM_PRESETS = {
    "generic": {"label": "Generic (http_requests_total + http_request_duration_seconds)",
                "service_label": "service",
                "requests": 'sum by ($label) (rate(http_requests_total[$window]))',
                "errors": 'sum by ($label) (rate(http_requests_total{status=~"5.."}[$window]))',
                "latency": 'histogram_quantile($quantile, sum by ($label, le) (rate(http_request_duration_seconds_bucket[$window]))) * 1000'},
    "otel": {"label": "OpenTelemetry semantic conventions (http.server.request.duration)",
             "service_label": "job",
             "requests": 'sum by ($label) (rate(http_server_request_duration_seconds_count[$window]))',
             "errors": 'sum by ($label) (rate(http_server_request_duration_seconds_count{http_response_status_code=~"5.."}[$window]))',
             "latency": 'histogram_quantile($quantile, sum by ($label, le) (rate(http_server_request_duration_seconds_bucket[$window]))) * 1000'},
    "spring": {"label": "Spring Boot / Micrometer (http_server_requests_seconds)",
               "service_label": "job",
               "requests": 'sum by ($label) (rate(http_server_requests_seconds_count[$window]))',
               "errors": 'sum by ($label) (rate(http_server_requests_seconds_count{status=~"5.."}[$window]))',
               "latency": 'histogram_quantile($quantile, sum by ($label, le) (rate(http_server_requests_seconds_bucket[$window]))) * 1000'},
    "node": {"label": "Node.js prom-client / express-prom-bundle",
             "service_label": "job",
             "requests": 'sum by ($label) (rate(http_request_duration_seconds_count[$window]))',
             "errors": 'sum by ($label) (rate(http_request_duration_seconds_count{status_code=~"5.."}[$window]))',
             "latency": 'histogram_quantile($quantile, sum by ($label, le) (rate(http_request_duration_seconds_bucket[$window]))) * 1000'},
    "nginx_ingress": {"label": "ingress-nginx controller",
                      "service_label": "ingress",
                      "requests": 'sum by ($label) (rate(nginx_ingress_controller_requests[$window]))',
                      "errors": 'sum by ($label) (rate(nginx_ingress_controller_requests{status=~"5.."}[$window]))',
                      "latency": 'histogram_quantile($quantile, sum by ($label, le) (rate(nginx_ingress_controller_request_duration_seconds_bucket[$window]))) * 1000'},
    "istio": {"label": "Istio service mesh",
              "service_label": "destination_service_name",
              "requests": 'sum by ($label) (rate(istio_requests_total{reporter="destination"}[$window]))',
              "errors": 'sum by ($label) (rate(istio_requests_total{reporter="destination",response_code=~"5.."}[$window]))',
              "latency": 'histogram_quantile($quantile, sum by ($label, le) (rate(istio_request_duration_milliseconds_bucket{reporter="destination"}[$window])))'},
    "linkerd": {"label": "Linkerd service mesh",
                "service_label": "deployment",
                "requests": 'sum by ($label) (rate(response_total{direction="inbound"}[$window]))',
                "errors": 'sum by ($label) (rate(response_total{direction="inbound",classification="failure"}[$window]))',
                "latency": 'histogram_quantile($quantile, sum by ($label, le) (rate(response_latency_ms_bucket{direction="inbound"}[$window])))'},
    "traefik": {"label": "Traefik",
                "service_label": "service",
                "requests": 'sum by ($label) (rate(traefik_service_requests_total[$window]))',
                "errors": 'sum by ($label) (rate(traefik_service_requests_total{code=~"5.."}[$window]))',
                "latency": 'histogram_quantile($quantile, sum by ($label, le) (rate(traefik_service_request_duration_seconds_bucket[$window]))) * 1000'},
}


class Prometheus(Source):
    kind, label, category = "prometheus", "Prometheus", "metrics"
    interval = 15
    query_language, query_example = "PromQL", 'sum by (service) (rate(http_requests_total{status=~"5.."}[1m]))'
    fields = [F("url", "Prometheus URL", required=True,
                help="Also works with Thanos, Mimir, Cortex, VictoriaMetrics, Grafana Cloud (…/api/prom)"),
              F("preset", "Metric names", "select", default="generic",
                options=[{"value": k, "label": v["label"]} for k, v in PROM_PRESETS.items()]),
              F("service_label", "Label that names the service", help="Defaults to the preset's"),
              F("requests_query", "Requests/second query (advanced)", "textarea"),
              F("errors_query", "Errors/second query (advanced)", "textarea"),
              F("latency_query", "Latency (ms) query, with $quantile (advanced)", "textarea"),
              F("alerts", "Import firing alerts (ALERTS series)", "bool", default=True),
              F("tenant", "Tenant / X-Scope-OrgID (Mimir, Cortex, Loki multi-tenant)"),
              *AUTH_FIELDS]

    def api_prefix(self) -> str:
        return "/api/v1"

    def preset(self) -> dict:
        p = dict(PROM_PRESETS.get(self.get("preset", "generic"), PROM_PRESETS["generic"]))
        for key in ("requests", "errors", "latency"):
            if self.get(f"{key}_query"):
                p[key] = self.get(f"{key}_query")
        p["service_label"] = self.get("service_label") or p["service_label"]
        return p

    def instant(self, client, expr: str) -> list[dict]:
        data = self.request(client, "POST", f"{self.api_prefix()}/query", data={"query": expr})
        if not isinstance(data, dict) or data.get("status") != "success":
            raise SourceError(f"query failed: {str(data)[:300]}")
        return data["data"]["result"]

    def by_service(self, client, expr: str, label: str) -> dict[str, float]:
        out = {}
        for r in self.instant(client, expr):
            name = r["metric"].get(label) or service_from_labels(r["metric"], "")
            try:
                v = float(r["value"][1])
            except (ValueError, TypeError, KeyError):
                continue
            if name and v == v:  # skip NaN
                out[name] = out.get(name, 0.0) + v
        return out

    def render(self, expr: str, p: dict, quantile: float | None = None) -> str:
        window = f"{max(60, self.interval * 4)}s"
        expr = expr.replace("$label", p["service_label"]).replace("$window", window)
        return expr.replace("$quantile", str(quantile)) if quantile is not None else expr

    def test(self) -> str:
        with self.client() as c:
            p = self.preset()
            services = self.by_service(c, self.render(p["requests"], p), p["service_label"])
        if not services:
            return ("Connected, but the requests query matched no series. Choose the preset that "
                    "matches your metric names, or write the queries yourself.")
        names = ", ".join(sorted(services)[:12])
        return f"Connected. Request metrics for {len(services)} services: {names}"

    def poll(self, state):
        p = self.preset()
        interval = float(self.get("interval_seconds", self.interval))
        metrics, events = [], []
        with self.client() as c:
            req = self.by_service(c, self.render(p["requests"], p), p["service_label"])
            err = self.by_service(c, self.render(p["errors"], p), p["service_label"])
            lat = {q: self.by_service(c, self.render(p["latency"], p, q), p["service_label"])
                   for q in (0.5, 0.95, 0.99)}
            for svc, rate in req.items():
                count = rate * interval
                errors = min(err.get(svc, 0.0) * interval, count)
                metrics.append({"service": svc, "count": round(count), "errors": round(errors),
                                "p50_ms": round(lat[0.5].get(svc, 0.0), 1),
                                "p95_ms": round(lat[0.95].get(svc, 0.0), 1),
                                "max_ms": round(lat[0.99].get(svc, 0.0), 1)})
            if self.get("alerts", True) in (True, "true", "1"):
                firing = []
                for r in self.instant(c, 'ALERTS{alertstate="firing"}'):
                    labels = r["metric"]
                    firing.append({"service": labels.get(p["service_label"]) or service_from_labels(labels),
                                   "kind": "alert", "status": "firing",
                                   "severity": severity_of(labels.get("severity"), "error"),
                                   "title": labels.get("alertname", "alert"),
                                   "fingerprint": json.dumps(labels, sort_keys=True),
                                   "active_until": utcnow() + timedelta(minutes=3),
                                   "detail": {"labels": labels}})
                events = firing + resolve_missing(state, firing)
        return {"metrics": metrics, "events": events}, state

    def query(self, q, minutes=15):
        end = time.time()
        step = max(15, int(minutes * 60 / 40))
        with self.client() as c:
            data = self.request(c, "POST", f"{self.api_prefix()}/query_range",
                                data={"query": q, "start": end - minutes * 60, "end": end, "step": step})
        if data.get("status") != "success":
            raise SourceError(str(data)[:300])
        return [{"labels": r["metric"],
                 "points": [[datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M:%S"),
                             round(float(v), 4)] for t, v in r["values"]][-40:]}
                for r in data["data"]["result"][:20]]


# ---------------------------------------------------------------- Loki

LOKI_ERROR_FILTER = r'|~ "(?i)(error|exception|fatal|panic|traceback|critical|level=(err|crit))"'
LOKI_SERVICE_LABELS = ("service_name", "service", "app", "application", "job", "container",
                       "container_name", "compose_service", "unit", "pod")


class Loki(Source):
    kind, label, category = "loki", "Grafana Loki", "logs"
    interval = 10
    query_language, query_example = "LogQL", '{service_name="checkout"} |= "error"'
    fields = [F("url", "Loki URL", required=True, help="e.g. http://loki:3100 or Grafana Cloud logs URL"),
              F("selector", "Stream selector", help='Default: every stream with a service label, e.g. {app=~".+"}'),
              F("filter", "Line filter for errors", default=LOKI_ERROR_FILTER),
              F("service_label", "Label that names the service", help="Detected automatically"),
              F("tenant", "Tenant / X-Scope-OrgID"), *AUTH_FIELDS]

    def base(self) -> str:
        return "/loki/api/v1"

    def service_label(self, client, state) -> str:
        if self.get("service_label"):
            return self.get("service_label")
        if state.get("service_label"):
            return state["service_label"]
        labels = self.request(client, "GET", f"{self.base()}/labels").get("data") or []
        label = next((l for l in LOKI_SERVICE_LABELS if l in labels), labels[0] if labels else "job")
        state["service_label"] = label
        return label

    def test(self):
        with self.client() as c:
            state = {}
            label = self.service_label(c, state)
            values = self.request(c, "GET", f"{self.base()}/label/{label}/values").get("data") or []
        return f"Connected. Services by '{label}': {', '.join(values[:12]) or '(none yet)'}"

    def poll(self, state):
        now_ns = time.time_ns()
        with self.client() as c:
            label = self.service_label(c, state)
            selector = self.get("selector") or f'{{{label}=~".+"}}'
            start = int(state.get("cursor_ns") or now_ns - 60 * 10**9)
            data = self.request(c, "GET", f"{self.base()}/query_range", params={
                "query": f"{selector} {self.get('filter') or ''}".strip(), "start": start,
                "end": now_ns, "limit": 1000, "direction": "forward"})
        logs, newest = [], start
        for stream in data.get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            svc = labels.get(label) or service_from_labels(labels)
            for ts, line, *_ in stream.get("values", []):
                newest = max(newest, int(ts))
                rec = _maybe_json(line)
                if labels.get("level") or labels.get("detected_level"):
                    rec.setdefault("level", labels.get("level") or labels.get("detected_level"))
                log = log_from_dict(rec, svc)
                log["ts"] = log["ts"] or int(ts)
                log["fields"] = {**labels, **log["fields"]}
                logs.append(log)
        state["cursor_ns"] = newest + 1 if logs else max(start, now_ns - 5 * 60 * 10**9)
        return {"logs": logs}, state

    def query(self, q, minutes=15):
        end = time.time_ns()
        with self.client() as c:
            data = self.request(c, "GET", f"{self.base()}/query_range", params={
                "query": q, "start": end - minutes * 60 * 10**9, "end": end, "limit": 100,
                "direction": "backward"})
        result = data.get("data", {})
        if result.get("resultType") == "streams":
            lines = [{"t": datetime.fromtimestamp(int(ts) / 1e9, timezone.utc).strftime("%H:%M:%S"),
                      "labels": s.get("stream"), "line": line[:600]}
                     for s in result.get("result", []) for ts, line, *_ in s.get("values", [])]
            return sorted(lines, key=lambda l: l["t"], reverse=True)[:100]
        return [{"labels": r.get("metric"), "points": [[datetime.fromtimestamp(float(t), timezone.utc)
                                                        .strftime("%H:%M:%S"), v] for t, v in r.get("values", [])][-40:]}
                for r in result.get("result", [])[:20]]


def _maybe_json(line: str) -> dict:
    if line.startswith("{"):
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                return rec
        except json.JSONDecodeError:
            pass
    return {"message": line}


# ---------------------------------------------------------------- Grafana

class Grafana(Source):
    kind, label, category = "grafana", "Grafana", "metrics, logs, alerts"
    interval = 15
    query_language = "PromQL or LogQL (prefix with prom: or loki:)"
    query_example = 'loki:{app="checkout"} |= "error"'
    fields = [F("url", "Grafana URL", required=True),
              F("token", "Service account token", "secret", required=True,
                help="Viewer role is enough"),
              F("prometheus_uid", "Prometheus data source UID", help="Detected automatically"),
              F("loki_uid", "Loki data source UID", help="Detected automatically"),
              F("preset", "Metric names", "select", default="generic",
                options=Prometheus.fields[1]["options"]),
              F("service_label", "Label that names the service"),
              F("alerts", "Import Grafana alerts", "bool", default=True),
              F("verify_tls", "Verify TLS certificates", "bool", default=True)]

    def headers(self):
        return {"User-Agent": "tracewise-collector/1.0", "Authorization": f"Bearer {self.get('token')}"}

    def datasources(self, client) -> dict[str, str]:
        found = {}
        for ds in self.request(client, "GET", "/api/datasources"):
            if ds.get("type") in ("prometheus", "loki") and ds["type"] not in found:
                found[ds["type"]] = ds["uid"]
        return found

    def delegate(self, cls, uid):
        cfg = {**self.config, "url": f"{self.get('url').rstrip('/')}/api/datasources/proxy/uid/{uid}",
               "bearer_token": None}
        src = cls(cfg, {"bearer_token": self.get("token")}, self.transport)
        return src

    def uids(self, state):
        if not state.get("uids"):
            with self.client() as c:
                state["uids"] = self.datasources(c)
        uids = dict(state["uids"])
        if self.get("prometheus_uid"):
            uids["prometheus"] = self.get("prometheus_uid")
        if self.get("loki_uid"):
            uids["loki"] = self.get("loki_uid")
        return uids

    def test(self):
        with self.client() as c:
            health = self.request(c, "GET", "/api/health")
            ds = self.datasources(c)
        parts = [f"Grafana {health.get('version', '')} reachable"]
        uids = {**ds, **{k: self.get(f"{k}_uid") for k in ("prometheus", "loki") if self.get(f"{k}_uid")}}
        if uids.get("prometheus"):
            parts.append("Prometheus: " + self.delegate(Prometheus, uids["prometheus"]).test())
        if uids.get("loki"):
            parts.append("Loki: " + self.delegate(Loki, uids["loki"]).test())
        if not uids:
            parts.append("no Prometheus or Loki data source found; only alerts will be imported")
        return ". ".join(parts)

    def poll(self, state):
        uids = self.uids(state)
        out = {"metrics": [], "logs": [], "events": []}
        for kind, cls in (("prometheus", Prometheus), ("loki", Loki)):
            if uids.get(kind):
                sub = self.delegate(cls, uids[kind])
                if kind == "prometheus":
                    sub.config["alerts"] = False
                records, state[kind] = sub.poll(state.get(kind) or {})
                for k, v in records.items():
                    out[k].extend(v)
        if self.get("alerts", True) in (True, "true", "1"):
            with self.client() as c:
                items = self.request(c, "GET", "/api/alertmanager/grafana/api/v2/alerts",
                                     params={"active": "true", "silenced": "false", "inhibited": "false"})
            firing = am_alerts(items if isinstance(items, list) else [])
            out["events"] += firing + resolve_missing(state, firing)
        return out, state

    def query(self, q, minutes=15):
        uids = self.uids({})
        lang, _, expr = q.partition(":")
        if lang not in ("prom", "loki"):
            lang, expr = ("loki" if q.lstrip().startswith("{") else "prom"), q
        kind = "prometheus" if lang == "prom" else "loki"
        if not uids.get(kind):
            raise SourceError(f"Grafana has no {kind} data source")
        return self.delegate(Prometheus if kind == "prometheus" else Loki, uids[kind]).query(expr, minutes)


# ---------------------------------------------------------------- Alertmanager

class Alertmanager(Source):
    kind, label, category = "alertmanager", "Prometheus Alertmanager", "alerts"
    interval = 15
    fields = [F("url", "Alertmanager URL", required=True), *AUTH_FIELDS]

    def test(self):
        with self.client() as c:
            status = self.request(c, "GET", "/api/v2/status")
            alerts = self.request(c, "GET", "/api/v2/alerts", params={"active": "true"})
        return (f"Connected to Alertmanager {status.get('versionInfo', {}).get('version', '')}; "
                f"{len(alerts)} active alerts")

    def poll(self, state):
        with self.client() as c:
            items = self.request(c, "GET", "/api/v2/alerts",
                                 params={"active": "true", "silenced": "false", "inhibited": "false"})
        firing = am_alerts(items)
        return {"events": firing + resolve_missing(state, firing)}, state


# ---------------------------------------------------------------- Elasticsearch / OpenSearch

class Elasticsearch(Source):
    kind, label, category = "elasticsearch", "Elasticsearch / OpenSearch", "logs"
    interval = 10
    query_language = "Lucene query string"
    query_example = 'service.name:checkout AND log.level:error'
    fields = [F("url", "Cluster URL", required=True, help="Elastic Cloud, self-hosted, or OpenSearch"),
              F("index", "Index pattern", default="logs-*,filebeat-*,fluent-bit*,logstash-*"),
              F("query", "Which documents are errors",
                default='log.level:(error OR ERROR OR critical OR fatal) OR level:(error OR ERROR OR '
                        'critical OR fatal) OR severity:(error OR ERROR) OR message:(Traceback OR Exception)'),
              F("timestamp_field", "Timestamp field", default="@timestamp"),
              F("service_field", "Service field", help="Default: service.name, kubernetes.labels.app, …"),
              F("api_key", "API key (Elastic)", "secret"),
              *AUTH_FIELDS]

    def headers(self):
        h = super().headers()
        if self.get("api_key"):
            h["Authorization"] = f"ApiKey {self.get('api_key')}"
        return h

    def search(self, client, body: dict) -> list[dict]:
        index = self.get("index").replace(" ", "")
        data = self.request(client, "POST", f"/{index}/_search",
                            params={"ignore_unavailable": "true", "allow_no_indices": "true"}, json=body)
        return data.get("hits", {}).get("hits", [])

    def to_log(self, hit: dict) -> dict:
        doc = hit.get("_source") or {}
        svc = first(doc, self.get("service_field")) if self.get("service_field") else None
        log = log_from_dict(doc, svc)
        log["ts"] = first(doc, self.get("timestamp_field")) or log["ts"]
        log["fields"]["_index"] = hit.get("_index")
        return log

    def test(self):
        with self.client() as c:
            info = self.request(c, "GET", "/")
            hits = self.search(c, {"size": 1, "query": {"query_string": {"query": self.get("query")}}})
        version = info.get("version", {}) if isinstance(info, dict) else {}
        flavour = version.get("distribution", "elasticsearch")
        return (f"Connected to {flavour} {version.get('number', '')}; "
                f"{'found' if hits else 'no'} matching error documents in {self.get('index')}")

    def poll(self, state):
        ts_field = self.get("timestamp_field")
        since = state.get("cursor") or iso(utcnow() - timedelta(minutes=1))
        with self.client() as c:
            hits = self.search(c, {
                "size": 500, "sort": [{ts_field: {"order": "asc"}}],
                "query": {"bool": {"filter": [{"range": {ts_field: {"gte": since}}},
                                              {"query_string": {"query": self.get("query")}}]}}})
        seen = set(state.get("seen") or [])
        fresh = [h for h in hits if h.get("_id") not in seen]
        if hits:
            last = first(hits[-1].get("_source") or {}, ts_field) or since
            state["cursor"] = last if isinstance(last, str) else iso(to_ts(last))
            state["seen"] = [h["_id"] for h in hits
                             if first(h.get("_source") or {}, ts_field) == last][-200:]
        return {"logs": [self.to_log(h) for h in fresh]}, state

    def query(self, q, minutes=15):
        ts_field = self.get("timestamp_field")
        with self.client() as c:
            hits = self.search(c, {
                "size": 50, "sort": [{ts_field: {"order": "desc"}}],
                "query": {"bool": {"filter": [
                    {"range": {ts_field: {"gte": f"now-{minutes}m"}}},
                    {"query_string": {"query": q}}]}}})
        return [{k: v for k, v in self.to_log(h).items() if v not in (None, {}, "")} for h in hits]


# ---------------------------------------------------------------- Datadog

class Datadog(Source):
    kind, label, category = "datadog", "Datadog", "logs, metrics, monitors"
    interval = 20
    query_language = "Datadog log search syntax (or metrics:<query>)"
    query_example = "service:checkout status:error"
    fields = [F("site", "Site", "select", required=True, default="datadoghq.com",
                options=[{"value": s, "label": s} for s in (
                    "datadoghq.com", "us3.datadoghq.com", "us5.datadoghq.com", "datadoghq.eu",
                    "ap1.datadoghq.com", "ddog-gov.com")]),
              F("api_key", "API key", "secret", required=True),
              F("app_key", "Application key", "secret", required=True),
              F("logs_query", "Which logs are errors", default="status:(error OR critical OR emergency OR alert)"),
              F("span_name", "APM span name for request metrics", default="http.request",
                help="e.g. flask.request, express.request, servlet.request, rack.request"),
              F("monitors", "Import triggered monitors", "bool", default=True)]

    def headers(self):
        return {"DD-API-KEY": self.get("api_key"), "DD-APPLICATION-KEY": self.get("app_key"),
                "User-Agent": "tracewise-collector/1.0"}

    def client(self, base_url=None, headers=None, timeout=20):
        return super().client(base_url or f"https://api.{self.get('site')}", headers, timeout)

    def test(self):
        with self.client() as c:
            self.request(c, "GET", "/api/v1/validate")
            logs = self.search_logs(c, self.get("logs_query"), utcnow() - timedelta(hours=1), 1)
        return f"API key valid; {'found' if logs else 'no'} error logs in the last hour"

    def search_logs(self, c, query, since, limit):
        data = self.request(c, "POST", "/api/v2/logs/events/search", json={
            "filter": {"query": query, "from": iso(since), "to": "now"},
            "sort": "timestamp", "page": {"limit": limit}})
        return data.get("data") or []

    def to_log(self, item):
        a = item.get("attributes") or {}
        inner = a.get("attributes") or {}
        err = inner.get("error") or {}
        rec = {**{k: v for k, v in inner.items() if not isinstance(v, (dict, list))},
               "message": a.get("message") or err.get("message") or "", "level": a.get("status"),
               "timestamp": a.get("timestamp"), "trace": err.get("stack")}
        log = log_from_dict(rec, a.get("service") or tags_to_dict(a.get("tags")).get("service") or a.get("host"))
        return log

    def series(self, c, q, start, end) -> dict[str, float]:
        data = self.request(c, "GET", "/api/v1/query", params={"from": int(start), "to": int(end), "query": q})
        out = {}
        for s in data.get("series", []):
            svc = tags_to_dict(s.get("scope", "")).get("service")
            pts = [p[1] for p in s.get("pointlist", []) if p[1] is not None]
            if svc and pts:
                out[svc] = pts[-1]
        return out

    def poll(self, state):
        out = {"logs": [], "metrics": [], "events": []}
        since = to_ts(state.get("cursor")) if state.get("cursor") else utcnow() - timedelta(minutes=1)
        with self.client() as c:
            items = self.search_logs(c, self.get("logs_query"), since, 500)
            seen = set(state.get("seen") or [])
            fresh = [i for i in items if i.get("id") not in seen]
            out["logs"] = [self.to_log(i) for i in fresh]
            if items:
                state["cursor"] = (items[-1].get("attributes") or {}).get("timestamp")
                state["seen"] = [i.get("id") for i in items[-200:]]
            end = time.time()
            span = self.get("span_name")
            hits = self.series(c, f"sum:trace.{span}.hits{{*}} by {{service}}.as_count()", end - 120, end)
            errs = self.series(c, f"sum:trace.{span}.errors{{*}} by {{service}}.as_count()", end - 120, end)
            p95 = self.series(c, f"p95:trace.{span}{{*}} by {{service}}", end - 120, end)
            p50 = self.series(c, f"p50:trace.{span}{{*}} by {{service}}", end - 120, end)
            for svc, n in hits.items():
                out["metrics"].append({"service": svc, "count": round(n), "errors": round(errs.get(svc, 0)),
                                       "p50_ms": round(p50.get(svc, 0) * 1000, 1),
                                       "p95_ms": round(p95.get(svc, 0) * 1000, 1)})
            if self.get("monitors", True) in (True, "true", "1"):
                firing = []
                for m in self.request(c, "GET", "/api/v1/monitor", params={"group_states": "alert"}):
                    if m.get("overall_state") not in ("Alert", "No Data"):
                        continue
                    tags = tags_to_dict(m.get("tags"))
                    firing.append({"service": tags.get("service") or m.get("name"), "kind": "alert",
                                   "status": "firing", "severity": severity_of(m.get("priority"), "error"),
                                   "title": m.get("name"), "fingerprint": f"dd:{m.get('id')}",
                                   "active_until": utcnow() + timedelta(minutes=3),
                                   "detail": {"query": m.get("query"), "state": m.get("overall_state")}})
                out["events"] = firing + resolve_missing(state, firing)
        return out, state

    def query(self, q, minutes=15):
        with self.client() as c:
            if q.startswith("metrics:"):
                end = time.time()
                data = self.request(c, "GET", "/api/v1/query",
                                    params={"from": int(end - minutes * 60), "to": int(end), "query": q[8:]})
                return [{"scope": s.get("scope"), "points": [[datetime.fromtimestamp(p[0] / 1000, timezone.utc)
                                                              .strftime("%H:%M:%S"), p[1]] for p in s.get("pointlist", [])][-40:]}
                        for s in data.get("series", [])[:20]]
            items = self.search_logs(c, q, utcnow() - timedelta(minutes=minutes), 50)
            return [self.to_log(i) for i in items]


# ---------------------------------------------------------------- New Relic

class NewRelic(Source):
    kind, label, category = "newrelic", "New Relic", "logs, metrics"
    interval = 30
    query_language, query_example = "NRQL", "SELECT count(*) FROM TransactionError FACET appName SINCE 15 minutes ago"
    fields = [F("account_id", "Account ID", required=True),
              F("api_key", "User API key (NRAK-…)", "secret", required=True),
              F("region", "Region", "select", default="us",
                options=[{"value": "us", "label": "US"}, {"value": "eu", "label": "EU"}]),
              F("logs_where", "Which logs are errors",
                default="level IN ('error', 'ERROR', 'critical', 'CRITICAL', 'fatal', 'FATAL')"),
              F("metrics", "Import APM request metrics (Transaction)", "bool", default=True)]

    def nrql(self, q: str) -> list[dict]:
        url = "https://api.eu.newrelic.com/graphql" if self.get("region") == "eu" else "https://api.newrelic.com/graphql"
        with self.client(url, {"API-Key": self.get("api_key")}) as c:
            data = self.request(c, "POST", "", json={
                "query": "query($id: Int!, $q: Nrql!) { actor { account(id: $id) { nrql(query: $q) { results } } } }",
                "variables": {"id": int(self.get("account_id")), "q": q}})
        if data.get("errors"):
            raise SourceError(data["errors"][0].get("message", str(data["errors"]))[:300])
        return data["data"]["actor"]["account"]["nrql"]["results"]

    def test(self):
        rows = self.nrql("SELECT uniques(appName) FROM Transaction SINCE 1 hour ago")
        apps = (rows[0].get("uniques.appName") if rows else None) or []
        return f"Connected. APM apps in the last hour: {', '.join(apps[:12]) or '(none)'}"

    def poll(self, state):
        since = int(state.get("cursor") or (time.time() - 60) * 1000)
        rows = self.nrql(f"SELECT * FROM Log WHERE {self.get('logs_where')} SINCE {since} UNTIL NOW LIMIT 1000")
        logs = []
        for r in rows:
            log = log_from_dict(r, r.get("service.name") or r.get("entity.name") or r.get("appName"))
            log["trace"] = log["trace"] or r.get("error.stack")
            logs.append(log)
        if rows:
            state["cursor"] = max(int(r.get("timestamp", since)) for r in rows) + 1
        metrics = []
        if self.get("metrics", True) in (True, "true", "1"):
            for r in self.nrql(f"SELECT count(*) AS requests, filter(count(*), WHERE error IS true) AS errors, "
                               f"percentile(duration, 50, 95, 99) FROM Transaction FACET appName "
                               f"SINCE {self.interval} seconds ago"):
                pct = r.get("percentile.duration") or {}
                metrics.append({"service": r.get("facet") or r.get("appName"), "count": r.get("requests", 0),
                                "errors": r.get("errors", 0), "p50_ms": (pct.get("50") or 0) * 1000,
                                "p95_ms": (pct.get("95") or 0) * 1000, "max_ms": (pct.get("99") or 0) * 1000})
        return {"logs": logs, "metrics": metrics}, state

    def query(self, q, minutes=15):
        if "since" not in q.lower():
            q = f"{q} SINCE {minutes} minutes ago"
        return self.nrql(q)[:100]


# ---------------------------------------------------------------- AWS CloudWatch

class CloudWatch(Source):
    kind, label, category = "cloudwatch", "AWS CloudWatch", "logs, alarms"
    interval = 20
    query_language = "CloudWatch Logs Insights"
    query_example = "fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc"
    fields = [F("region", "Region", required=True, default="us-east-1"),
              F("log_groups", "Log groups (comma separated)", required=True,
                help="Service names come from the group: /ecs/checkout -> checkout"),
              F("filter_pattern", "Filter pattern", default="?ERROR ?Error ?error ?Exception ?FATAL ?Traceback ?CRITICAL"),
              F("access_key_id", "Access key ID", help="Leave empty to use the instance/pod role"),
              F("secret_access_key", "Secret access key", "secret"),
              F("session_token", "Session token", "secret"),
              F("alarms", "Import alarms in ALARM state", "bool", default=True)]

    def boto(self, service):
        import boto3
        kw = {"region_name": self.get("region")}
        if self.get("access_key_id"):
            kw.update(aws_access_key_id=self.get("access_key_id"),
                      aws_secret_access_key=self.get("secret_access_key"),
                      aws_session_token=self.get("session_token"))
        return boto3.client(service, **kw)

    def groups(self):
        return [g.strip() for g in self.get("log_groups", "").split(",") if g.strip()]

    def test(self):
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            logs = self.boto("logs")
            found = []
            for g in self.groups():
                r = logs.describe_log_groups(logGroupNamePrefix=g, limit=1)
                if r.get("logGroups"):
                    found.append(g)
        except (BotoCoreError, ClientError) as exc:
            raise SourceError(str(exc)[:300])
        missing = set(self.groups()) - set(found)
        return f"Connected. Log groups found: {', '.join(found) or 'none'}" + (
            f"; not found: {', '.join(sorted(missing))}" if missing else "")

    def poll(self, state):
        from .receivers import cloudwatch_service
        logs_client = self.boto("logs")
        cursors = state.setdefault("cursors", {})
        out_logs = []
        for g in self.groups():
            start = int(cursors.get(g) or (time.time() - 60) * 1000)
            kw = {"logGroupName": g, "startTime": start, "limit": 500}
            if self.get("filter_pattern"):
                kw["filterPattern"] = self.get("filter_pattern")
            resp = logs_client.filter_log_events(**kw)
            newest = start
            for ev in resp.get("events", []):
                newest = max(newest, ev["timestamp"])
                log = log_from_dict(_maybe_json(ev.get("message", "")),
                                    cloudwatch_service(g, ev.get("logStreamName", "")))
                log["ts"] = log["ts"] or ev["timestamp"]
                log["fields"].update({"log_group": g, "log_stream": ev.get("logStreamName")})
                out_logs.append(log)
            cursors[g] = newest + 1 if resp.get("events") else start
        events = []
        if self.get("alarms", True) in (True, "true", "1"):
            firing = []
            for a in self.boto("cloudwatch").describe_alarms(StateValue="ALARM").get("MetricAlarms", []):
                dims = {d["Name"]: d["Value"] for d in a.get("Dimensions", [])}
                svc = next((dims[k] for k in ("ServiceName", "FunctionName", "TargetGroup", "LoadBalancer",
                                              "DBInstanceIdentifier", "InstanceId") if k in dims), a["AlarmName"])
                firing.append({"service": svc, "kind": "alert", "status": "firing", "severity": "error",
                               "title": f"{a['AlarmName']}: {a.get('StateReason', '')}"[:500],
                               "fingerprint": a["AlarmArn"], "active_until": utcnow() + timedelta(minutes=3),
                               "detail": {"metric": a.get("MetricName"), "namespace": a.get("Namespace"),
                                          "dimensions": dims}})
            events = firing + resolve_missing(state, firing)
        return {"logs": out_logs, "events": events}, state

    def query(self, q, minutes=15):
        logs = self.boto("logs")
        end = int(time.time())
        qid = logs.start_query(logGroupNames=self.groups(), startTime=end - minutes * 60, endTime=end,
                               queryString=q, limit=100)["queryId"]
        for _ in range(30):
            r = logs.get_query_results(queryId=qid)
            if r["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
                return [{f["field"]: f["value"] for f in row} for row in r.get("results", [])]
            time.sleep(1)
        raise SourceError("Logs Insights query didn't finish in 30s")


# ---------------------------------------------------------------- Google Cloud Logging

class GCPLogging(Source):
    kind, label, category = "gcp_logging", "Google Cloud Logging", "logs"
    interval = 15
    query_language, query_example = "Cloud Logging filter", 'resource.type="cloud_run_revision" AND severity>=ERROR'
    fields = [F("project_id", "Project ID", required=True),
              F("service_account_json", "Service account key (JSON)", "secret", required=True,
                help="Needs roles/logging.viewer"),
              F("filter", "Which entries are errors", default="severity>=ERROR")]

    def token(self) -> str:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        try:
            info = json.loads(self.get("service_account_json"))
        except (TypeError, json.JSONDecodeError):
            raise SourceError("service account key isn't valid JSON")
        now = int(time.time())
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")  # noqa: E731
        header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = b64(json.dumps({"iss": info["client_email"], "aud": info.get("token_uri", "https://oauth2.googleapis.com/token"),
                                 "scope": "https://www.googleapis.com/auth/logging.read",
                                 "iat": now, "exp": now + 3600}).encode())
        key = serialization.load_pem_private_key(info["private_key"].encode(), password=None)
        sig = b64(key.sign(header + b"." + claims, padding.PKCS1v15(), hashes.SHA256()))
        with httpx.Client(timeout=20, transport=self.transport) as c:
            r = c.post(info.get("token_uri", "https://oauth2.googleapis.com/token"),
                       data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                             "assertion": (header + b"." + claims + b"." + sig).decode()})
        if r.status_code != 200:
            raise SourceError(f"Google rejected the service account: {r.text[:200]}")
        return r.json()["access_token"]

    def entries(self, flt: str, limit: int, order="timestamp asc") -> list[dict]:
        with self.client("https://logging.googleapis.com", {"Authorization": f"Bearer {self.token()}"}) as c:
            data = self.request(c, "POST", "/v2/entries:list", json={
                "resourceNames": [f"projects/{self.get('project_id')}"], "filter": flt,
                "orderBy": order, "pageSize": limit})
        return data.get("entries", [])

    @staticmethod
    def to_log(e: dict) -> dict:
        rl = (e.get("resource") or {}).get("labels") or {}
        labels = e.get("labels") or {}
        svc = (rl.get("service_name") or rl.get("function_name") or labels.get("k8s-pod/app")
               or labels.get("k8s-pod/app_kubernetes_io/name") or rl.get("container_name")
               or rl.get("module_id") or e.get("logName", "").split("/")[-1])
        payload = e.get("jsonPayload") or {"message": e.get("textPayload") or json.dumps(e.get("protoPayload") or {})[:2000]}
        log = log_from_dict({**payload, "severity": e.get("severity")}, svc)
        log["ts"] = e.get("timestamp")
        log["fields"].update({"insert_id": e.get("insertId"), "resource": (e.get("resource") or {}).get("type")})
        return log

    def test(self):
        found = self.entries(f'{self.get("filter")} AND timestamp>="{iso(utcnow() - timedelta(hours=1))}"', 1)
        return f"Connected to {self.get('project_id')}; {'found' if found else 'no'} error entries in the last hour"

    def poll(self, state):
        since = state.get("cursor") or iso(utcnow() - timedelta(minutes=1))
        entries = self.entries(f'{self.get("filter")} AND timestamp>="{since}"', 1000)
        seen = set(state.get("seen") or [])
        fresh = [e for e in entries if e.get("insertId") not in seen]
        if entries:
            state["cursor"] = entries[-1].get("timestamp")
            state["seen"] = [e.get("insertId") for e in entries if e.get("timestamp") == state["cursor"]]
        return {"logs": [self.to_log(e) for e in fresh]}, state

    def query(self, q, minutes=15):
        return [self.to_log(e) for e in self.entries(
            f'({q}) AND timestamp>="{iso(utcnow() - timedelta(minutes=minutes))}"', 50, "timestamp desc")]


# ---------------------------------------------------------------- Azure Monitor

AZURE_KQL = """union isfuzzy=true
 (AppExceptions | project TimeGenerated, Service=AppRoleName, Level="error",
    Message=strcat(ExceptionType, ": ", OuterMessage), Trace=tostring(Details)),
 (AppTraces | where SeverityLevel >= 3 | project TimeGenerated, Service=AppRoleName,
    Level=iff(SeverityLevel >= 4, "critical", "error"), Message, Trace=""),
 (ContainerLogV2 | where LogLevel in~ ("error", "critical", "fatal")
    | project TimeGenerated, Service=ContainerName, Level=tostring(LogLevel),
      Message=tostring(LogMessage), Trace="")"""


class AzureMonitor(Source):
    kind, label, category = "azure_monitor", "Azure Monitor / Application Insights", "logs"
    interval = 30
    query_language, query_example = "KQL", "AppRequests | where Success == false | summarize count() by AppRoleName"
    fields = [F("tenant_id", "Tenant ID", required=True), F("client_id", "Client ID", required=True),
              F("client_secret", "Client secret", "secret", required=True),
              F("workspace_id", "Log Analytics workspace ID", required=True),
              F("kql", "Error query (must project TimeGenerated, Service, Level, Message, Trace)",
                "textarea", default=AZURE_KQL)]

    def token(self) -> str:
        with httpx.Client(timeout=20, transport=self.transport) as c:
            r = c.post(f"https://login.microsoftonline.com/{self.get('tenant_id')}/oauth2/v2.0/token",
                       data={"grant_type": "client_credentials", "client_id": self.get("client_id"),
                             "client_secret": self.get("client_secret"),
                             "scope": "https://api.loganalytics.io/.default"})
        if r.status_code != 200:
            raise SourceError(f"Azure AD rejected the app credentials: {r.text[:200]}")
        return r.json()["access_token"]

    def kql(self, q: str, timespan: str) -> list[dict]:
        with self.client("https://api.loganalytics.io", {"Authorization": f"Bearer {self.token()}"}) as c:
            data = self.request(c, "POST", f"/v1/workspaces/{self.get('workspace_id')}/query",
                                json={"query": q, "timespan": timespan})
        tables = data.get("tables") or []
        if not tables:
            return []
        cols = [c["name"] for c in tables[0]["columns"]]
        return [dict(zip(cols, row)) for row in tables[0]["rows"]]

    def test(self):
        rows = self.kql(self.get("kql") + " | take 1", "PT1H")
        return f"Connected to workspace; {'found' if rows else 'no'} errors in the last hour"

    def poll(self, state):
        since = state.get("cursor") or iso(utcnow() - timedelta(minutes=1))
        rows = self.kql(f"{self.get('kql')}\n| where TimeGenerated > datetime({since})"
                        f" | order by TimeGenerated asc | take 1000", "PT1H")
        logs = [{"service": r.get("Service") or "unknown", "ts": r.get("TimeGenerated"),
                 "level": level_of(r.get("Level")), "message": r.get("Message") or "",
                 "trace": r.get("Trace") or None, "fields": {}} for r in rows]
        if rows:
            state["cursor"] = rows[-1]["TimeGenerated"]
        return {"logs": logs}, state

    def query(self, q, minutes=15):
        return self.kql(q, f"PT{minutes}M")[:100]


# ---------------------------------------------------------------- Sentry

class Sentry(Source):
    kind, label, category = "sentry", "Sentry", "errors"
    interval = 30
    query_language, query_example = "Sentry issue search", "is:unresolved level:error"
    fields = [F("url", "Sentry URL", default="https://sentry.io", help="Or your self-hosted URL"),
              F("organization", "Organization slug", required=True),
              F("token", "Auth token", "secret", required=True, help="Scopes: event:read, project:read"),
              F("query", "Which issues", default="is:unresolved")]

    def headers(self):
        return {"Authorization": f"Bearer {self.get('token')}", "User-Agent": "tracewise-collector/1.0"}

    def issues(self, c, query, period="24h", limit=50):
        return self.request(c, "GET", f"/api/0/organizations/{self.get('organization')}/issues/",
                            params={"query": query, "statsPeriod": period, "sort": "date", "limit": limit})

    def test(self):
        with self.client() as c:
            org = self.request(c, "GET", f"/api/0/organizations/{self.get('organization')}/")
            issues = self.issues(c, self.get("query"), "24h", 5)
        return f"Connected to {org.get('name')}; {len(issues)}+ unresolved issues seen in 24h"

    def poll(self, state):
        from .alerts import _sentry_trace
        counts = state.setdefault("counts", {})
        logs = []
        with self.client() as c:
            for issue in self.issues(c, self.get("query"), "1h", 100):
                total, prev = int(issue.get("count") or 0), counts.get(issue["id"])
                counts[issue["id"]] = total
                if prev is not None and total <= prev:
                    continue
                if prev is None and to_ts(issue.get("lastSeen")) < utcnow() - timedelta(minutes=2):
                    continue  # old news on first sight
                trace = None
                try:
                    latest = self.request(c, "GET", f"/api/0/organizations/{self.get('organization')}"
                                                    f"/issues/{issue['id']}/events/latest/")
                    trace = _sentry_trace(latest)
                except SourceError:
                    pass
                logs.append({"service": (issue.get("project") or {}).get("slug") or "unknown",
                             "ts": issue.get("lastSeen"), "level": level_of(issue.get("level")),
                             "message": issue.get("title") or "", "trace": trace,
                             "count": max(1, min(total - (prev or total - 1), 10_000)),
                             "fields": {"culprit": issue.get("culprit"), "sentry_url": issue.get("permalink"),
                                        "issue": issue.get("shortId")}})
        state["counts"] = dict(list(counts.items())[-500:])
        return {"logs": logs}, state

    def query(self, q, minutes=15):
        with self.client() as c:
            return [{k: i.get(k) for k in ("shortId", "title", "culprit", "level", "count", "userCount",
                                           "firstSeen", "lastSeen", "permalink")}
                    | {"project": (i.get("project") or {}).get("slug")}
                    for i in self.issues(c, q, "24h" if minutes > 60 else f"{max(minutes, 1)}m", 25)]


# ---------------------------------------------------------------- Splunk

class Splunk(Source):
    kind, label, category = "splunk", "Splunk", "logs"
    interval = 20
    query_language, query_example = "SPL", 'search index=main sourcetype=checkout ERROR | stats count by host'
    fields = [F("url", "Splunk management URL", required=True, help="e.g. https://splunk.example.com:8089"),
              F("token", "Authentication token", "secret"),
              F("username", "Username"), F("password", "Password", "secret"),
              F("search", "Error search", default='search index=* (log_level=ERROR OR level=error OR '
                                                    'severity=ERROR OR "Traceback" OR "Exception")'),
              F("service_field", "Field that names the service", default="service",
                help="Falls back to app, sourcetype, then host"),
              F("verify_tls", "Verify TLS certificates", "bool", default=True)]

    def headers(self):
        h = {"User-Agent": "tracewise-collector/1.0"}
        if self.get("token"):
            h["Authorization"] = f"Bearer {self.get('token')}"
        return h

    def export(self, search: str, earliest, latest="now") -> list[dict]:
        with self.client(timeout=60) as c:
            text = self.request(c, "POST", "/services/search/jobs/export", data={
                "search": search if search.lstrip().startswith(("search", "|")) else f"search {search}",
                "earliest_time": earliest, "latest_time": latest, "output_mode": "json"})
        rows = []
        for line in (text if isinstance(text, str) else json.dumps(text)).splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("result"):
                rows.append(obj["result"])
        return rows

    def to_log(self, r):
        svc = first(r, self.get("service_field"), "service", "app", "sourcetype", "host")
        rec = _maybe_json(r.get("_raw", ""))
        rec = {**{k: v for k, v in r.items() if not k.startswith("_")}, **rec}
        log = log_from_dict(rec, svc)
        log["ts"] = r.get("_time") or log["ts"]
        return log

    def test(self):
        with self.client() as c:
            info = self.request(c, "GET", "/services/server/info", params={"output_mode": "json"})
        version = (info.get("entry") or [{}])[0].get("content", {}).get("version", "")
        return f"Connected to Splunk {version}"

    def poll(self, state):
        earliest = state.get("cursor") or f"{int(time.time() - 60)}"
        rows = self.export(self.get("search") + " | sort 0 _time", earliest)
        state["cursor"] = f"{time.time():.3f}"
        return {"logs": [self.to_log(r) for r in rows[:1000]]}, state

    def query(self, q, minutes=15):
        return [self.to_log(r) for r in self.export(q, f"-{minutes}m")[:100]]


# ---------------------------------------------------------------- HTTP checks

class HTTPCheck(Source):
    kind, label, category = "http_check", "HTTP health checks", "uptime"
    interval = 5
    fields = [F("targets", "Endpoints, one per line: <service> <url>", "textarea", required=True,
                help="e.g. checkout https://shop.example.com/healthz"),
              F("timeout_seconds", "Timeout (seconds)", "int", default=5),
              F("requests_per_check", "Requests per check", "int", default=2),
              F("verify_tls", "Verify TLS certificates", "bool", default=True)]

    def targets(self) -> list[tuple[str, str]]:
        out = []
        for line in str(self.get("targets", "")).splitlines():
            parts = line.split()
            if len(parts) == 1:
                from urllib.parse import urlparse
                out.append((urlparse(parts[0]).hostname or parts[0], parts[0]))
            elif len(parts) >= 2:
                out.append((parts[0], parts[1]))
        return out

    def check(self, client, url) -> tuple[bool, float, str]:
        started = time.perf_counter()
        try:
            r = client.get(url)
            ok = r.status_code < 500
            detail = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"[:200]
        return ok, (time.perf_counter() - started) * 1000, detail

    def test(self):
        results = []
        with httpx.Client(timeout=float(self.get("timeout_seconds")), verify=bool(self.get("verify_tls", True)),
                          transport=self.transport, follow_redirects=True) as c:
            for svc, url in self.targets():
                ok, ms, detail = self.check(c, url)
                results.append(f"{svc}: {detail} in {ms:.0f} ms")
        if not results:
            raise SourceError("no targets")
        return "; ".join(results)

    def poll(self, state):
        metrics, events, logs = [], [], []
        n = max(1, int(self.get("requests_per_check")))
        with httpx.Client(timeout=float(self.get("timeout_seconds")), verify=bool(self.get("verify_tls", True)),
                          transport=self.transport, follow_redirects=True) as c:
            for svc, url in self.targets():
                results = [self.check(c, url) for _ in range(n)]
                lat = sorted(r[1] for r in results)
                errors = sum(1 for r in results if not r[0])
                metrics.append({"service": svc, "count": n, "errors": errors, "p50_ms": round(lat[len(lat) // 2], 1),
                                "p95_ms": round(lat[-1], 1), "max_ms": round(lat[-1], 1)})
                down = errors == n
                was_down = svc in (state.get("down") or [])
                if down:
                    events.append({"service": svc, "kind": "down", "status": "firing", "severity": "critical",
                                   "title": f"{url} is down: {results[-1][2]}", "fingerprint": f"down:{url}",
                                   "active_until": utcnow() + timedelta(seconds=60), "detail": {"url": url}})
                    logs.append({"service": svc, "level": "error", "message": f"health check failed: {results[-1][2]}",
                                 "route": url})
                elif was_down:
                    events.append({"service": svc, "kind": "down", "status": "resolved", "severity": "info",
                                   "title": f"{url} is back", "fingerprint": f"down:{url}"})
                state.setdefault("down", [])
                state["down"] = [s for s in state["down"] if s != svc] + ([svc] if down else [])
        return {"metrics": metrics, "events": events, "logs": logs}, state


KINDS: dict[str, type[Source]] = {cls.kind: cls for cls in (
    Prometheus, Loki, Grafana, Alertmanager, Elasticsearch, Datadog, NewRelic, CloudWatch,
    GCPLogging, AzureMonitor, Sentry, Splunk, HTTPCheck)}
KINDS["opensearch"] = Elasticsearch
