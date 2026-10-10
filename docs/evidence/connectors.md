# Connector evidence (Oct 10)

## Live lab (`integrations/lab`), fault on in `lab-stock`

Each real shipper sent the same `KeyError: 'APPLE'` stack trace into Tracewise, and each pull
source was polled successfully:

| Path | Delivered |
|---|---|
| Promtail → `/loki/api/v1/push` (snappy protobuf) | 868 error lines with traces |
| Fluent Bit → `/v1/ingest/logs` and `/es/_bulk` | 849 / 851 |
| Vector → http, loki, splunk_hec, datadog_logs sinks | 869 / 893 / 907 / 926 |
| OTel Collector → `/otlp/v1/traces` (protobuf) | request metrics, `otel-orders → otel-stock` edge, 868 exception logs |
| Alertmanager → `/v1/ingest/alerts/alertmanager` | `HighErrorRate` firing for both services |
| Pull: Prometheus | 1001/1037 requests, ~48% errors, p95, plus `ALERTS` |
| Pull: Loki, Grafana (data-source proxy), Alertmanager, OpenSearch, HTTP checks | logs, metrics and alerts as above |
| Bad Prometheus port / bad Grafana token | `failed`: "Connection refused" / "401: credentials rejected" |

### Agent run (incident #49, $0.15, 5 turns)

Opened 30s after the fault, from the Alertmanager alert. The agent:
1. Called `list_events`, then `search_logs` (which found traces from 5 shippers), `list_sources`
   and Prometheus-backed `get_metrics`.
2. Found `stock[sku.upper()]` against lowercase keys at app.py:45.
3. Identified lab-orders (#50) as collateral damage.
4. Escalated with the exact fix and the PromQL to verify it, because the lab services aren't
   deployer-managed.

With the alert still firing, no duplicate incidents opened during the next 150s.

## Host agent on this machine

| Command | Result |
|---|---|
| `watch pm2` (crashing Node app) | `TypeError` with its 4-line trace, `FATAL`, restart events (3→48) |
| `watch systemd --user` (failing unit) | `KeyError: 'sku'` with its trace; restart events 18→27 |
| `watch docker` | "container tw-lab-box exited with code 3", plus its stderr error |
| `watch file` (access log) | 40 requests, 8 × 502, p50 43 ms / p95 83 ms; 5xx lines collapsed (count 8) |
| `watch syslog`, `watch http`, `exec`, `deploy`, `login` (bad and good key) | all as expected |

The detector opened incidents #42–46 from these events: the pm2 crash loop, the systemd restart
loop, the container exit, the down health check and the failed job.

## Unit tests

`backend/tests/test_connectors.py`: 42 passed. They cover levels, timestamps, traces, ECS fields,
all alert/deploy webhooks, SNS signature checks, syslog/logplex, Loki protobuf, OTLP (including
cumulative histograms), and Prometheus, Datadog, New Relic, GCP, Azure, Sentry, Splunk and
HTTP checks against mocked APIs.

## Bugs found by the live test, all fixed

1. Postgres deadlocks between concurrent writers: psycopg's `executemany` runs as one implicit
   transaction, so unsorted service upserts collided.
2. An alert still firing reopened a new incident every ~90s after escalation. Alerts are now
   linked to the incident they caused.
3. A service with one stray data point counted as having a baseline.
4. Services from a disabled pull source looked "silent".
5. systemd user units were attributed to `user@1000`.
6. `exec` lost the last stack trace on exit.
7. ECS `service: {name}` objects weren't resolved.
8. "Error: ..." lines weren't detected as errors.
9. Splunk's NDJSON export failed to parse.

## Cost

Before fixes 2 and 3 existed, test alerts kept reopening incidents and the agent worked each one:
27 agent runs (#9–48) cost $4.86. After the fixes, one real fault produced two incidents ($0.30).
