# Tracewise

An on-call agent that runs without anyone watching. When something breaks in a running system,
Tracewise works out what broke and why, fixes it itself, checks that the system really recovered,
and writes up the incident with the evidence behind each conclusion. Every resolved incident
becomes memory for the next one.

## How it works

```
Shopfront (7 services) ──telemetry, deploys──▶ Tracewise API ──▶ Postgres
      ▲                                              │
      │ rollback / flags / restart                   ▼
      └──────────────── agent worker ◀──── detector (opens incidents)
                         plan → investigate → hypothesize → act → verify → resolve
```

- **Shopfront** (`demo/`): a small store: gateway, checkout, payments, bank, catalog,
  inventory and orders. Each service reports request metrics, error logs and calls to other
  services every 2 seconds. A deployer runs every service at a chosen git commit and keeps the
  deploy history; a traffic generator keeps it busy.
- **Detector** (`backend/tracewise/detector.py`): compares each service with its own
  15-minute baseline (error rate, p95 latency, silence) with no hand-set thresholds. Unhealthy
  services that are connected are grouped into one incident.
- **Agent** (`backend/tracewise/agent/`): Claude (Opus 5.5) in a tool loop. Read-only tools
  investigate (health, metrics, logs, dependencies, deploys, commits, code, memory); action tools
  change the system (feature flag, rollback, restart); `verify_recovery` watches the services
  until they stay healthy. It can't resolve without a passing verification.
- **Reliability:** the conversation is saved after every turn and incidents are held by a
  renewable lease, so if a worker dies another picks up the run where it stopped. Actions are
  keyed per tool call, so a resumed run never applies one twice. Budgets cap turns, cost and
  actions, and the agent must verify each action before taking another.
- **Changes during an incident** (new deploys, newly affected services) are passed to the agent
  as `[environment update]` messages, and it re-plans.

## Connected coding agents (fix forward)

A rollback stops the bleeding but throws away the feature. Teams connect their own coding agent
and Tracewise hands it the fix:

1. **Connect an account** (`POST /v1/connections`): **Claude** with an Anthropic API key from the
   Claude Console, or **Cursor** with a Cursor API key. Keys are encrypted at rest
   (`TW_SECRET_KEY`), and the runner checks each one with its provider. Claude connects through
   an API key rather than a claude.ai login, because Anthropic doesn't allow third-party products
   to offer claude.ai login or subscription limits.
2. Once production is stable, the incident agent calls `request_code_fix` with the evidence. The
   **runner** creates a git worktree on `tracewise/fix-incident-<id>-<service>` and runs the
   connected agent headless (`claude -p` or Cursor's `agent -p`). The agent gets only its own API
   key and a throwaway home directory, and for Claude a narrow tool allowlist (edit files,
   pytest, git, `entire graph`).
3. The agent finds the code with Entire Graph, fixes it, adds a regression test and commits.
   Entire's hooks attach an `Entire-Checkpoint` trailer, so the commit carries the session that
   produced it (`entire checkpoint explain <sha>`).
4. The runner doesn't trust the agent's summary: it runs the tests itself and records the diff,
   commit, checkpoint and cost.
5. If the tests pass, the incident agent calls `deploy_fix` (main is fast-forwarded too), then
   verifies again. With `TW_AUTO_DEPLOY_FIXES=false`, the fix waits on its branch for review.

| Endpoint | What |
|---|---|
| `GET /v1/providers` | Supported agents and what credential each needs |
| `GET/POST /v1/connections`, `DELETE /v1/connections/{id}` | Manage connected accounts (keys are never returned) |
| `POST /v1/connections/{id}/test`, `POST /v1/connections/{id}/default` | Re-check a key, choose the default agent |
| `GET /v1/fix-jobs`, `GET /v1/fix-jobs/{id}` | Fix jobs with live log, diff, test output and checkpoint |

## Connectors: telemetry from the tools teams already use

Shopfront is the demo, but Tracewise isn't tied to it. Logs, metrics, alerts and deploys come in from
wherever a team already has them, and the detector and agent treat every source the same way.
Details and how each one was verified are in [docs/CONNECTORS.md](docs/CONNECTORS.md).

- **Host agent** (`cli/tracewise`): one stdlib-only Python file that watches pm2, systemd, Docker
  or Podman, Kubernetes, log files (nginx and Apache access logs become request metrics),
  syslog, HTTP checks, supervisord, macOS, or any wrapped command. It reports crashes, restarts,
  OOM kills and deploys, and rejoins multi-line stack traces. Run
  `tracewise detect && tracewise init && tracewise run`.
- **Push:** OpenTelemetry (OTLP), the Loki push API (Promtail, Alloy), the Elasticsearch bulk API
  (Fluent Bit, Logstash), Splunk HEC, Datadog intake, JSON/NDJSON (Vector, Fluentd), Heroku
  drains, Firehose (CloudWatch Logs) and syslog. Alert webhooks are supported for Alertmanager,
  Grafana, Datadog, PagerDuty, Opsgenie, Sentry, CloudWatch/SNS, New Relic, Azure and GCP.
  Deploy webhooks are supported for GitHub, GitLab, Vercel and Argo CD.
- **Pull:** Prometheus (with presets for common metric names), Loki, Grafana, Alertmanager,
  Elasticsearch/OpenSearch, Datadog, New Relic, CloudWatch, Google Cloud Logging,
  Azure Monitor, Sentry, Splunk and HTTP checks. The agent can query any of them live with
  `query_source`, in that tool's own language.

`integrations/lab/` runs the real tools (Prometheus, Alertmanager, Loki, Promtail, Grafana,
OpenSearch, Fluent Bit, Vector and the OTel Collector) against a two-service app with a fault
switch. Start it with `integrations/lab/up.sh`.

## Tenancy

- A **workspace** is a team: its members, their roles and its coding-agent accounts.
- A **project** is a system the team runs. Every service, metric, log, alert, deploy, incident, fix and memory
  belongs to exactly one project, and every API query is filtered by it.
- **Ingest keys** (`twk_…`) belong to a project and decide where incoming data lands. Create them under
  Settings → Project; only a hash is stored and the key is shown once. Keys can't read other projects or
  manage accounts.
- The agent runs inside the incident's project: its telemetry, its memory, and that project's repository and
  deploy integration. Projects without a deploy integration get a full investigation and a handover.
- Repository paths and deployer URLs are set by the operator, never through the API.
- Upgrading an older single-tenant database moves its data into a "Shopfront demo" workspace whose project keeps
  the old `TW_INGEST_KEY`. People listed in `TW_BOOTSTRAP_OWNERS` become its owners when they sign in.

## Accounts, workspaces and email

- **Sign in** with a one-time email code, Google or GitHub (`/login`). Sessions are httpOnly
  cookies in the web app; the API checks them on every `/v1` route except ingest.
- **Workspaces** have owners, admins, members and viewers. Admins invite people by email,
  manage roles and projects, and connect sources and coding agents.
- **Email** for every account and team event: sign-in code, welcome, new-device sign-in, linked
  Google/GitHub, workspace created, invitation, invitation accepted, joined, role changed, removed,
  project created, coding agent connected/disconnected, source connected, and incident resolved or
  escalated (by each person's notification setting). Templates follow the iac project's
  Vercel-style layout; every email is logged and previewable under Settings → Email log.
- Configure in `.env`: `SMTP_HOST/PORT/USERNAME/PASSWORD/FROM` (STARTTLS on 587 or TLS on 465),
  `GOOGLE_CLIENT_ID/SECRET`, `GITHUB_CLIENT_ID/SECRET`, and `TW_WEB_URL`. OAuth callback URLs are
  `<TW_WEB_URL>/api/auth/callback/google` and `/api/auth/callback/github`.

## Where neatlogs, Entire and cfo.ai fit

| Tool | Role |
|---|---|
| **neatlogs** | One trace per incident run (`tracing.py`): every Claude call (auto-instrumented), every tool call as a span, retries and errors. Used to find and compare failing runs while improving the agent. |
| **Entire** | Fix commits written by connected agents carry an `Entire-Checkpoint`; the incident agent reads it with `entire checkpoint explain`. The agent's code tools call `entire graph`: `commit` (which functions and config keys a deploy changed), `search`, `impact` (blast radius of a symbol), `explain` (stack trace → file:line), and checkpoint lookup on commits with an `Entire-Checkpoint` trailer. |
| **cfo.ai** | Business plan built in cfo.ai over its MCP server: pricing, cost per incident (measured, traced in neatlogs), revenue and runway, with a downside scenario. Summary in `docs/business/README.md`; live model at https://app.cfo.ai/s/cPgf01AUStZFzZd3. |

## Run it

Requirements: Docker with Compose, Python 3.10+, the Entire CLI with the graph plugin
(`curl -fsSL https://entire.io/install.sh | bash && entire plugin install graph`), and an
Anthropic API key.

```sh
cp .env.example .env                 # set ANTHROPIC_API_KEY, NEATLOGS_API_KEY, TW_INGEST_KEY
demo/seed_shopfront.sh               # creates demo/shopfront, a git repo with some history
scripts/vendor-entire.sh             # copies the Entire CLI into the backend images
scripts/vendor-agents.sh             # copies the Claude Code and Cursor CLIs into the runner image
docker compose up -d --build
```

| Port | What |
|---|---|
| 19103 | Tracewise web console (incidents, live timeline and replay, services, deploys, fixes, sources, coding agents) |
| 19100 | Tracewise API (`/v1/incidents`, `/v1/health`, `/v1/topology`, `/v1/stream` SSE) |
| 19101 | Shopfront gateway |
| 19102 | Shopfront deployer (`/services`, `/deploy`, `/rollback`, `/flags`) |
| 19110 | Postgres |
| 19114 | Syslog receiver (TCP and UDP) |

Give the detector about two minutes of traffic to learn a baseline, then break something:

```sh
scripts/scenarios.py list
scripts/scenarios.py run bad-config     # waits until the agent resolves or escalates
scripts/scenarios.py reset
```

## Scenarios (the evaluation set)

| Scenario | What breaks | What a good agent does |
|---|---|---|
| `bad-config` | A payments deploy cuts the bank timeout from 800 ms to 50 ms | Links errors to the deploy, finds the changed key, rolls back, verifies |
| `code-bug` | A checkout deploy crashes on carts without gift wrap | Finds the stack trace and the commit, rolls back (or fixes), verifies |
| `bank-outage` | The bank goes down; nothing was deployed | Doesn't roll back innocent services; switches to the backup processor |
| `change-mid-incident` | `bad-config`, then an unrelated catalog deploy lands mid-investigation | Doesn't blame the new deploy; finishes the original fix |
| `repeat` | `bad-config` again | Recognises it from memory and fixes it faster |

Results from each run are appended to `docs/evidence/scenarios.md`.

## Built with AI assistance

Parts of this project were written with Claude Code.
