"""Setup instructions for every push integration, filled in with this install's URL and key."""

PUSH = [
    # ---- host agent
    {"kind": "agent", "label": "Tracewise agent (pm2, systemd, Docker, Kubernetes, log files, syslog)",
     "category": "host", "endpoint": "/v1/ingest/logs",
     "setup": """curl -fsSL {base}/agent/install.sh | sh      # one stdlib-only Python file
tracewise login --url {base} --key {key}
tracewise detect          # finds pm2 apps, systemd units, containers, pods and log files
tracewise init            # writes tracewise.yaml from what it found
tracewise run             # or: tracewise watch pm2 | systemd --unit nginx | docker | kubernetes | file /var/log/app.log"""},
    {"kind": "deploy-cli", "label": "Deploys from CI (any CI system)", "category": "deploys",
     "endpoint": "/v1/ingest/deploys",
     "setup": """# after your deploy step:
tracewise deploy --service checkout --sha "$GIT_COMMIT"     # author/message read from git
# or without the agent:
curl -X POST {base}/v1/ingest/deploys/generic -H 'x-ingest-key: {key}' \\
  -H 'content-type: application/json' -d '{{"service":"checkout","sha":"'$GIT_COMMIT'"}}'"""},

    # ---- OpenTelemetry
    {"kind": "otlp", "label": "OpenTelemetry (SDKs or Collector): traces, logs, metrics",
     "category": "traces, logs, metrics", "endpoint": "/otlp",
     "setup": """# Any OpenTelemetry SDK, no Collector needed:
OTEL_EXPORTER_OTLP_ENDPOINT={base}/otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_HEADERS=x-ingest-key={key}

# Or in an OpenTelemetry Collector:
exporters:
  otlphttp/tracewise:
    endpoint: {base}/otlp
    headers: {{x-ingest-key: {key}}}
service:
  pipelines:
    traces:  {{receivers: [otlp], exporters: [otlphttp/tracewise]}}
    logs:    {{receivers: [otlp, filelog], exporters: [otlphttp/tracewise]}}
    metrics: {{receivers: [otlp], exporters: [otlphttp/tracewise]}}"""},

    # ---- log shippers
    {"kind": "promtail", "label": "Promtail / Grafana Alloy / Docker Loki driver (Loki push API)",
     "category": "logs", "endpoint": "/loki/api/v1/push",
     "setup": """# Promtail
clients:
  - url: {base}/loki/api/v1/push
    bearer_token: {key}

# Grafana Alloy
loki.write "tracewise" {{
  endpoint {{
    url = "{base}/loki/api/v1/push"
    bearer_token = "{key}"
  }}
}}

# Docker logging driver (docker plugin install grafana/loki-docker-driver)
docker run --log-driver=loki --log-opt loki-url="{base_auth}/loki/api/v1/push" ..."""},
    {"kind": "vector", "label": "Vector", "category": "logs", "endpoint": "/v1/ingest/logs",
     "setup": """[sinks.tracewise]
type = "http"
inputs = ["your_logs"]
uri = "{base}/v1/ingest/logs"
encoding.codec = "json"
request.headers.x-ingest-key = "{key}"
compression = "gzip"
# Vector's loki, elasticsearch and splunk_hec sinks work too (see those entries)"""},
    {"kind": "fluent-bit", "label": "Fluent Bit", "category": "logs", "endpoint": "/v1/ingest/logs",
     "setup": """[OUTPUT]
    Name        http
    Match       *
    Host        {host}
    Port        {port}
    URI         /v1/ingest/logs
    Format      json
    Header      x-ingest-key {key}
    tls         {tls}
    compress    gzip
# Kubernetes: add the kubernetes filter; service names come from the app labels."""},
    {"kind": "fluentd", "label": "Fluentd", "category": "logs", "endpoint": "/v1/ingest/logs",
     "setup": """<match **>
  @type http
  endpoint {base}/v1/ingest/logs
  headers {{"x-ingest-key":"{key}"}}
  json_array true
  <format>
    @type json
  </format>
</match>"""},
    {"kind": "logstash", "label": "Logstash / Beats (via Elasticsearch output)", "category": "logs",
     "endpoint": "/es/_bulk",
     "setup": """output {{
  elasticsearch {{
    hosts => ["{base}/es"]
    user => "tracewise"
    password => "{key}"
    ilm_enabled => false
    manage_template => false
  }}
}}
# Fluent Bit's es output works the same way: Host {host}, Port {port}, Path /es, HTTP_User x, HTTP_Passwd {key}"""},
    {"kind": "splunk-hec", "label": "Splunk HTTP Event Collector (anything that sends to HEC)",
     "category": "logs", "endpoint": "/splunk/services/collector",
     "setup": """HEC URL:   {base}/splunk/services/collector
HEC token: {key}
# e.g. Vector `splunk_hec_logs` sink, Fluent Bit `splunk` output, OpenTelemetry `splunk_hec` exporter"""},
    {"kind": "datadog-intake", "label": "Datadog log forwarding (Vector datadog_logs, Fluent Bit datadog)",
     "category": "logs", "endpoint": "/datadog/api/v2/logs",
     "setup": """# Vector
[sinks.tracewise]
type = "datadog_logs"
inputs = ["your_logs"]
endpoint = "{base}/datadog"
default_api_key = "{key}"
# Fluent Bit: [OUTPUT] Name datadog, Host {host}, Port {port}, apikey {key}"""},
    {"kind": "syslog", "label": "Syslog (rsyslog, syslog-ng, network devices, Render, Papertrail-style)",
     "category": "logs", "endpoint": "udp/tcp :{syslog_port}",
     "setup": """# Tracewise listens for RFC 5424 / RFC 3164 syslog on port {syslog_port} (TCP and UDP).
# rsyslog: /etc/rsyslog.d/90-tracewise.conf
*.* @@{host}:{syslog_port}
# syslog-ng
destination d_tracewise {{ network("{host}" port({syslog_port}) transport("tcp")); }};
# Or run `tracewise watch syslog --listen udp://0.0.0.0:5514` on a host in your network."""},
    {"kind": "logplex", "label": "Heroku log drain", "category": "logs", "endpoint": "/v1/ingest/logplex",
     "setup": "heroku drains:add '{base_auth}/v1/ingest/logplex?service=<app>' -a <app>"},
    {"kind": "http", "label": "Any JSON / NDJSON over HTTP (Vercel/Netlify/Fly drains, scripts)",
     "category": "logs", "endpoint": "/v1/ingest/logs",
     "setup": """curl -X POST '{base}/v1/ingest/logs?service=checkout' -H 'x-ingest-key: {key}' \\
  -d '{{"level":"error","message":"payment failed","trace":"..."}}'
# Field names are detected: message/msg/log, level/severity/status, timestamp/time/@timestamp,
# service/app/service.name/kubernetes.labels.app. Arrays and NDJSON batches are fine."""},
    {"kind": "firehose", "label": "AWS CloudWatch Logs (subscription -> Kinesis Firehose)",
     "category": "logs", "endpoint": "/v1/ingest/firehose",
     "setup": """# Firehose delivery stream, destination "HTTP endpoint":
#   URL: {base}/v1/ingest/firehose     Access key: {key}     Content encoding: GZIP
# Then subscribe each log group:
aws logs put-subscription-filter --log-group-name /ecs/checkout --filter-name tracewise \\
  --filter-pattern '' --destination-arn <firehose-arn> --role-arn <role-arn>
# Or use the CloudWatch pull connector instead (no Firehose needed)."""},

    # ---- alerts
    {"kind": "alertmanager-webhook", "label": "Prometheus Alertmanager webhook", "category": "alerts",
     "endpoint": "/v1/ingest/alerts/alertmanager",
     "setup": """receivers:
  - name: tracewise
    webhook_configs:
      - url: {base}/v1/ingest/alerts/alertmanager
        send_resolved: true
        http_config: {{authorization: {{credentials: {key}}}}}"""},
    {"kind": "grafana-webhook", "label": "Grafana Alerting contact point", "category": "alerts",
     "endpoint": "/v1/ingest/alerts/grafana",
     "setup": """Alerting > Contact points > Add > Webhook
  URL: {base}/v1/ingest/alerts/grafana
  Authorization header: Bearer {key}"""},
    {"kind": "datadog-webhook", "label": "Datadog monitors (Webhooks integration)", "category": "alerts",
     "endpoint": "/v1/ingest/alerts/datadog",
     "setup": """Integrations > Webhooks > New
  URL: {base}/v1/ingest/alerts/datadog?key={key}
  Payload:
  {{"id":"$ID","alert_id":"$ALERT_ID","title":"$EVENT_TITLE","status":"$ALERT_TRANSITION",
    "priority":"$PRIORITY","tags":"$TAGS","url":"$LINK","body":"$EVENT_MSG","date":"$DATE"}}
Then add @webhook-tracewise to your monitor messages."""},
    {"kind": "pagerduty-webhook", "label": "PagerDuty (v3 webhooks)", "category": "alerts",
     "endpoint": "/v1/ingest/alerts/pagerduty",
     "setup": "Integrations > Generic Webhooks (v3) > New: URL {base}/v1/ingest/alerts/pagerduty?key={key}, events incident.triggered + incident.resolved"},
    {"kind": "opsgenie-webhook", "label": "Opsgenie", "category": "alerts", "endpoint": "/v1/ingest/alerts/opsgenie",
     "setup": "Settings > Integrations > Webhook: URL {base}/v1/ingest/alerts/opsgenie?key={key}, add alert description/details"},
    {"kind": "sentry-webhook", "label": "Sentry alerts", "category": "alerts", "endpoint": "/v1/ingest/alerts/sentry",
     "setup": "Settings > Developer Settings > Internal Integration: Webhook URL {base}/v1/ingest/alerts/sentry?key={key}, enable Alert Rule Action + issue events. Or use the Sentry pull connector."},
    {"kind": "cloudwatch-sns", "label": "AWS CloudWatch alarms (SNS)", "category": "alerts",
     "endpoint": "/v1/ingest/alerts/cloudwatch",
     "setup": "aws sns subscribe --topic-arn <alarm-topic> --protocol https --notification-endpoint '{base}/v1/ingest/alerts/cloudwatch?key={key}'\n# Tracewise confirms the subscription and verifies every message's SNS signature."},
    {"kind": "newrelic-webhook", "label": "New Relic workflows", "category": "alerts", "endpoint": "/v1/ingest/alerts/newrelic",
     "setup": "Alerts > Destinations > Webhook: URL {base}/v1/ingest/alerts/newrelic?key={key}; use the default payload template."},
    {"kind": "azure-webhook", "label": "Azure Monitor action group", "category": "alerts", "endpoint": "/v1/ingest/alerts/azure",
     "setup": "Action group > Actions > Webhook: URI {base}/v1/ingest/alerts/azure?key={key}, enable the common alert schema."},
    {"kind": "gcp-webhook", "label": "Google Cloud Monitoring", "category": "alerts", "endpoint": "/v1/ingest/alerts/gcp",
     "setup": "Monitoring > Alerting > Edit notification channels > Webhooks: {base}/v1/ingest/alerts/gcp?key={key}"},
    {"kind": "generic-alert", "label": "Anything else (Uptime Kuma, Zabbix, Checkly, Better Stack, scripts)",
     "category": "alerts", "endpoint": "/v1/ingest/alerts/generic",
     "setup": """curl -X POST '{base}/v1/ingest/alerts/generic' -H 'x-ingest-key: {key}' \\
  -d '{{"service":"checkout","title":"p99 over 2s","status":"firing","severity":"critical","id":"checkout-latency"}}'
# send the same id with "status":"resolved" when it clears."""},

    # ---- deploys
    {"kind": "github-deploys", "label": "GitHub deployments / Actions", "category": "deploys",
     "endpoint": "/v1/ingest/deploys/github",
     "setup": "Repo > Settings > Webhooks: URL {base}/v1/ingest/deploys/github?key={key}, events: Deployment statuses and Workflow runs. Add ?service=<name> if the repo name isn't the service."},
    {"kind": "gitlab-deploys", "label": "GitLab deployments", "category": "deploys", "endpoint": "/v1/ingest/deploys/gitlab",
     "setup": "Settings > Webhooks: URL {base}/v1/ingest/deploys/gitlab?key={key}, trigger: Deployment events"},
    {"kind": "vercel-deploys", "label": "Vercel deployments", "category": "deploys", "endpoint": "/v1/ingest/deploys/vercel",
     "setup": "Team Settings > Webhooks: URL {base}/v1/ingest/deploys/vercel?key={key}, events: deployment.succeeded"},
    {"kind": "argocd-deploys", "label": "Argo CD notifications", "category": "deploys", "endpoint": "/v1/ingest/deploys/argocd",
     "setup": """service.webhook.tracewise: |
  url: {base}/v1/ingest/deploys/argocd?key={key}
template.app-deployed: |
  webhook:
    tracewise:
      method: POST
      body: '{{"service":"{{{{.app.metadata.name}}}}","sha":"{{{{.app.status.sync.revision}}}}","actor":"argocd"}}'"""},
]


def render(base: str, key: str, syslog_port: int) -> list[dict]:
    from urllib.parse import urlparse
    u = urlparse(base)
    host = u.hostname or "localhost"
    port = u.port or (443 if u.scheme == "https" else 80)
    base_auth = f"{u.scheme}://tracewise:{key}@{u.netloc}{u.path}".rstrip("/")
    out = []
    for item in PUSH:
        out.append({**item, "mode": "push",
                    "setup": item["setup"].format(base=base.rstrip("/"), key=key, host=host, port=port,
                                                  tls="On" if u.scheme == "https" else "Off",
                                                  base_auth=base_auth, syslog_port=syslog_port),
                    "endpoint": item["endpoint"].format(syslog_port=syslog_port)})
    return out
