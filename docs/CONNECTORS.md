# Connectors

Tracewise reads telemetry from the tools a team already runs. Every source is normalized into the
same four things: **logs** (with stack traces rejoined), **request metrics** (count, errors,
p50/p95), **events** (alerts, crashes, restarts, OOM kills, failed checks) and **deploys**. The
detector and the agent work on all of them the same way.

- `GET /v1/source-types` lists everything below, with setup snippets filled in for your install.
  The real ingest key is only shown to callers who send it.
- `GET /v1/sources` shows what's connected and receiving.
- `GET /v1/events` lists alerts and crashes.

The agent gets three tools for this data:
- `list_events`: alerts, crashes and restarts from every source.
- `list_sources`: what's connected and each source's query language.
- `query_source`: queries a connected tool live, in its own language (PromQL, LogQL, Lucene, NRQL,
  Logs Insights, KQL, SPL, Sentry search).

## How each one was verified

| Mark | Meaning |
|---|---|
| **live** | Ran against the real tool in `integrations/lab` or on this host |
| **mocked** | Unit test against the documented API shape (`backend/tests/test_connectors.py`, 42 tests) |
| **curl** | Hand-made request matching the documented payload |

## 1. Host agent (`cli/tracewise`)

A single Python 3.8+ file with no dependencies. Install it with
`curl -fsSL <tracewise>/agent/install.sh | sh`.

| Command | What it watches | Verified |
|---|---|---|
| `watch pm2` | Tails each app's log files, which keeps stack traces intact (`pm2 logs --json` flattens them). Reports restarts, `errored` state, and new git revisions as deploys | live: Node `TypeError` trace rejoined, restart count tracked |
| `watch systemd --unit X [--user]` | Follows `journalctl -o json`. Reports `NRestarts` increases and `failed` state | live (user unit): Python `KeyError` trace rejoined, restarts reported |
| `watch docker` (`--runtime podman`) | `docker logs -f` per container, plus `docker events`: exit codes, OOM, restarts, health checks, image changes as deploys | live: container exit code 3 reported, stderr error shipped |
| `watch kubernetes` | `kubectl logs -f` per container. Reports restarts with the reason (OOMKilled, Error), CrashLoopBackOff/ImagePullBackOff, and image changes as deploys | not run: no cluster on this host |
| `watch file PATH...` | `tail -F` that survives rotation. nginx/Apache access logs also become request metrics (count, 5xx, p50/p95 from `$request_time`) | live: 40 lines gave 8 errors and p95 83 ms |
| `watch syslog` | RFC 5424/3164 over UDP and TCP | live |
| `watch http URL` | Synthetic checks: request metrics, plus a `down` event | live |
| `watch supervisor` | `supervisorctl tail -f`, plus FATAL/BACKOFF/EXITED states | not run: supervisord isn't installed |
| `watch macos` | `log stream --style ndjson` | not run: Linux host |
| `exec --service X -- cmd` | Wraps any process (cron jobs, scripts, forever, nodemon), passes its output through, and reports a non-zero exit as a crash | live |
| `deploy --service X` | Records a deploy from any CI; author and message come from git | live |
| `detect` / `init` / `run` | Finds pm2 apps, systemd units, containers, kube context and web server logs, then writes `tracewise.json` | live on this host: 3 pm2 apps, 39 units, 160 containers, nginx/apache logs |

Shared behavior:
- Multi-line stack traces (Python, Java, Node, Go, .NET) are rejoined into one record.
- Identical lines within a flush are collapsed into one record with a count.
- Batches are gzipped, and failed sends are retried.
- A heartbeat registers the host in `/v1/sources`.

## 2. Push: tools send to Tracewise

| Endpoint | Speaks | Tested with |
|---|---|---|
| `/otlp/v1/{traces,logs,metrics}` | OTLP/HTTP, protobuf or JSON, gzip. Server spans become request metrics, client spans become dependency edges, exception events become error logs with traces. HTTP duration histograms are supported (cumulative or delta) | live: OpenTelemetry Collector 0.111 + Python SDK (`orders→stock` edge discovered) |
| `/loki/api/v1/push` | Loki push, snappy protobuf or JSON | live: Promtail 3.2 (protobuf), Vector `loki` sink |
| `/es/_bulk` (plus `/es/` info) | Elasticsearch bulk API | live: Fluent Bit `es` output |
| `/splunk/services/collector[/event,/raw]` | Splunk HEC | live: Vector `splunk_hec_logs` |
| `/datadog/api/v2/logs` | Datadog log intake | live: Vector `datadog_logs` |
| `/v1/ingest/logs` | Any JSON, array or NDJSON. Field names are detected (ECS, pino, bunyan, structlog, Vercel...) | live: Fluent Bit `http`, Vector `http` |
| `/v1/ingest/logplex` | Heroku log drains (RFC 6587 framing) | curl, plus unit test |
| `/v1/ingest/firehose` | AWS Kinesis Firehose HTTP endpoint, i.e. CloudWatch Logs subscriptions | curl (gzipped CloudWatch batch) |
| syslog `:19114` tcp/udp | rsyslog, syslog-ng, network gear | live (`nc`) |
| `/v1/ingest/alerts/{kind}` | Alert webhooks from alertmanager, grafana, datadog, pagerduty, opsgenie, sentry, cloudwatch (SNS, with signature check), newrelic, azure, gcp, and generic (also covers Uptime Kuma) | live: Alertmanager 0.27. Others: curl and unit tests |
| `/v1/ingest/deploys/{kind}` | Deploy webhooks from github, gitlab, vercel, argocd, generic | curl and unit tests |

Authentication accepts whatever the sender can send:
- the `x-ingest-key` header
- `Authorization: Bearer`, `Splunk` or `ApiKey`
- basic auth, with the key as the password
- `DD-API-KEY` or `X-Amz-Firehose-Access-Key`
- `?key=` in the URL

## 3. Pull: Tracewise reads from the tool

Connect a pull source with `POST /v1/sources {kind, name, config}`. The collector tests the
credentials, then polls on an interval. Secrets are encrypted at rest, and the poll position is
saved, so a restart continues where it left off.

| Kind | Reads | Verified |
|---|---|---|
| `prometheus` | Request rate, errors and p50/p95/p99 per service, plus `ALERTS`. Presets: generic, OpenTelemetry, Spring/Micrometer, Node prom-client, ingress-nginx, Istio, Linkerd, Traefik. Works with Thanos, Mimir, Cortex, VictoriaMetrics and Grafana Cloud | live (Prometheus 2.54), mocked |
| `loki` | Error lines; the service label is detected | live (Loki 3.2) |
| `grafana` | Prometheus and Loki through the data-source proxy (detected automatically), plus Grafana-managed alerts | live (Grafana 11.2 service-account token) |
| `alertmanager` | Active alerts | live |
| `elasticsearch` / `opensearch` | Error documents, using any index pattern or query | live (OpenSearch 2.17) |
| `datadog` | Logs search, APM trace metrics, monitors in Alert state | mocked |
| `newrelic` | NRQL for Log and Transaction | mocked |
| `cloudwatch` | Log groups (`FilterLogEvents`), alarms in ALARM; agent queries use Logs Insights | not tested (boto3; needs an AWS account) |
| `gcp_logging` | `entries:list`, using a service-account JWT signed locally | mocked |
| `azure_monitor` | Log Analytics KQL (App Insights, ContainerLogV2) | mocked |
| `sentry` | Issues, counting only new events, with the latest stack trace | mocked |
| `splunk` | Search export (SPL) | mocked |
| `http_check` | Endpoints polled from the server | live |

## Not covered yet

- Prometheus `remote_write`. Pull from the Prometheus API instead (works for Mimir, Thanos and VictoriaMetrics too).
- Windows Event Log.
- Kafka as a log source.
- Honeycomb's query API. Send it OTLP instead.
- **Actions on external services.** The agent can only roll back, restart or flag services that the
  Shopfront deployer manages. For services seen through these connectors it investigates and hands
  over with the exact command. Restarting through the host agent (pm2, systemctl, docker, kubectl
  rollout undo), behind an explicit opt-in, is the natural next step.
