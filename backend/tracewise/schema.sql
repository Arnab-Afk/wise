CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS services (
    name        text PRIMARY KEY,
    current_sha text,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now()
);

-- Who calls whom, learned from the services' own outgoing calls.
CREATE TABLE IF NOT EXISTS service_edges (
    src        text NOT NULL,
    dst        text NOT NULL,
    calls      bigint NOT NULL DEFAULT 0,
    errors     bigint NOT NULL DEFAULT 0,
    last_seen  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (src, dst)
);

-- One row per service per flush (about every 2s).
CREATE TABLE IF NOT EXISTS metric_points (
    service  text NOT NULL,
    ts       timestamptz NOT NULL,
    sha      text,
    count    int NOT NULL,
    errors   int NOT NULL,
    p50_ms   real NOT NULL,
    p95_ms   real NOT NULL,
    max_ms   real NOT NULL
);
CREATE INDEX IF NOT EXISTS metric_points_service_ts ON metric_points (service, ts DESC);

-- Edge stats per flush, so the agent can see which dependency is failing right now.
CREATE TABLE IF NOT EXISTS edge_points (
    src     text NOT NULL,
    dst     text NOT NULL,
    ts      timestamptz NOT NULL,
    calls   int NOT NULL,
    errors  int NOT NULL,
    avg_ms  real NOT NULL
);
CREATE INDEX IF NOT EXISTS edge_points_ts ON edge_points (ts DESC);

CREATE TABLE IF NOT EXISTS log_events (
    id       bigserial PRIMARY KEY,
    service  text NOT NULL,
    ts       timestamptz NOT NULL,
    sha      text,
    level    text NOT NULL,
    message  text NOT NULL,
    route    text,
    status   int,
    trace    text,
    fields   jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS log_events_service_ts ON log_events (service, ts DESC);

CREATE TABLE IF NOT EXISTS deploys (
    id           bigserial PRIMARY KEY,
    service      text NOT NULL,
    sha          text NOT NULL,
    prev_sha     text,
    author       text,
    author_email text,
    message      text,
    committed_at timestamptz,
    actor        text,
    reason       text,
    deployed_at  timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS deploys_service_at ON deploys (service, deployed_at DESC);

CREATE TABLE IF NOT EXISTS incidents (
    id           bigserial PRIMARY KEY,
    title        text NOT NULL,
    status       text NOT NULL DEFAULT 'open',  -- open, investigating, acting, verifying, resolved, escalated
    severity     text NOT NULL DEFAULT 'high',
    services     text[] NOT NULL,
    signals      jsonb NOT NULL DEFAULT '[]',
    summary      text,
    root_cause   text,
    fix          text,
    opened_at    timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz,
    lease_owner  text,
    lease_until  timestamptz,
    scenario     text
);
CREATE INDEX IF NOT EXISTS incidents_status ON incidents (status);

-- Everything that happened during an incident, in order. Streamed to the UI.
CREATE TABLE IF NOT EXISTS incident_steps (
    id           bigserial PRIMARY KEY,
    incident_id  bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    ts           timestamptz NOT NULL DEFAULT now(),
    kind         text NOT NULL,   -- detector, environment, thinking, tool, action, verify, plan, hypotheses, resolve, escalate, error
    phase        text,
    title        text NOT NULL,
    data         jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS incident_steps_incident ON incident_steps (incident_id, id);

-- The agent's conversation, persisted after every turn so a run can resume after a crash.
CREATE TABLE IF NOT EXISTS agent_runs (
    incident_id     bigint PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE,
    messages        jsonb NOT NULL DEFAULT '[]',
    turns           int NOT NULL DEFAULT 0,
    input_tokens    bigint NOT NULL DEFAULT 0,
    output_tokens   bigint NOT NULL DEFAULT 0,
    cost_usd        numeric(10, 4) NOT NULL DEFAULT 0,
    last_deploy_id  bigint NOT NULL DEFAULT 0,
    last_step_id    bigint NOT NULL DEFAULT 0,
    nudges          int NOT NULL DEFAULT 0,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);

-- Changes the agent made to the system. The key makes a retried tool call a no-op.
CREATE TABLE IF NOT EXISTS actions (
    id               bigserial PRIMARY KEY,
    incident_id      bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    idempotency_key  text NOT NULL UNIQUE,
    kind             text NOT NULL,
    target           text,
    params           jsonb NOT NULL DEFAULT '{}',
    status           text NOT NULL,   -- running, done, failed
    result           jsonb,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- What the team learned from each resolved incident.
CREATE TABLE IF NOT EXISTS memories (
    id           bigserial PRIMARY KEY,
    incident_id  bigint REFERENCES incidents(id) ON DELETE SET NULL,
    services     text[] NOT NULL,
    symptoms     text NOT NULL,
    root_cause   text NOT NULL,
    fix          text NOT NULL,
    outcome      text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    search       tsvector GENERATED ALWAYS AS (
        to_tsvector('english', symptoms || ' ' || root_cause || ' ' || fix)) STORED
);
CREATE INDEX IF NOT EXISTS memories_search ON memories USING gin (search);

-- Scenario runs from scripts/scenarios.py: the eval harness. New incidents are tagged with the
-- scenario that was running when they opened.
CREATE TABLE IF NOT EXISTS scenario_runs (
    id           bigserial PRIMARY KEY,
    name         text NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    incident_id  bigint REFERENCES incidents(id) ON DELETE SET NULL,
    result       jsonb
);

-- Coding agents the team has connected. The credential is encrypted with TW_SECRET_KEY.
CREATE TABLE IF NOT EXISTS connections (
    id              bigserial PRIMARY KEY,
    provider        text NOT NULL,          -- claude | cursor
    label           text NOT NULL,
    credential      bytea NOT NULL,
    credential_hint text NOT NULL,          -- last 4 characters, for display
    model           text,
    is_default      boolean NOT NULL DEFAULT false,
    status          text NOT NULL DEFAULT 'untested',   -- untested, ok, failed
    status_detail   text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_used_at    timestamptz
);

-- A coding agent asked to write a fix on its own branch.
CREATE TABLE IF NOT EXISTS fix_jobs (
    id              bigserial PRIMARY KEY,
    incident_id     bigint REFERENCES incidents(id) ON DELETE SET NULL,
    connection_id   bigint REFERENCES connections(id) ON DELETE SET NULL,
    provider        text NOT NULL,
    service         text NOT NULL,
    task            text NOT NULL,
    base_sha        text NOT NULL,
    branch          text NOT NULL,
    status          text NOT NULL DEFAULT 'queued',  -- queued, running, ready, failed
    commit_sha      text,
    checkpoint_id   text,
    tests_passed    boolean,
    test_output     text,
    diff            text,
    agent_summary   text,
    cost_usd        numeric(10, 4),
    log             text NOT NULL DEFAULT '',
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz,
    lease_until     timestamptz
);
CREATE INDEX IF NOT EXISTS fix_jobs_status ON fix_jobs (status);

-- ---------- connectors: telemetry from the tools teams already use ----------

ALTER TABLE log_events ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE log_events ADD COLUMN IF NOT EXISTS count int NOT NULL DEFAULT 1;  -- identical lines collapsed
ALTER TABLE metric_points ADD COLUMN IF NOT EXISTS source text;
CREATE INDEX IF NOT EXISTS log_events_ts ON log_events (ts DESC);

-- Where telemetry comes from. Pull sources (Prometheus, Loki, Datadog...) are polled by the
-- collector; push sources (OTLP, Loki push, webhooks, host agents) register themselves on first use.
CREATE TABLE IF NOT EXISTS sources (
    id               bigserial PRIMARY KEY,
    kind             text NOT NULL,
    name             text NOT NULL,
    mode             text NOT NULL,                  -- pull | push
    config           jsonb NOT NULL DEFAULT '{}',
    credential       bytea,                          -- encrypted JSON of the secret fields
    secret_fields    text[] NOT NULL DEFAULT '{}',
    enabled          boolean NOT NULL DEFAULT true,
    status           text NOT NULL DEFAULT 'testing', -- testing, ok, failed, receiving
    status_detail    text,
    state            jsonb NOT NULL DEFAULT '{}',    -- poll cursors
    poll_lease_until timestamptz,
    last_polled_at   timestamptz,
    last_received_at timestamptz,
    items_received   bigint NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (kind, name)
);

-- Alerts, crashes, restarts, OOM kills, failed health checks: things a source says happened.
-- Active error/critical events make a service unhealthy, like a metric anomaly does.
CREATE TABLE IF NOT EXISTS source_events (
    id            bigserial PRIMARY KEY,
    source        text NOT NULL,
    service       text NOT NULL,
    fingerprint   text NOT NULL,
    kind          text NOT NULL,       -- alert, crash, restart, oom, down, unhealthy, deploy_failed, info
    severity      text NOT NULL,       -- critical, error, warning, info
    status        text NOT NULL,       -- firing, resolved
    title         text NOT NULL,
    detail        jsonb NOT NULL DEFAULT '{}',
    started_at    timestamptz NOT NULL,
    last_seen     timestamptz NOT NULL,
    active_until  timestamptz NOT NULL,
    UNIQUE (source, fingerprint)
);
CREATE INDEX IF NOT EXISTS source_events_active ON source_events (active_until DESC);

-- The incident an alert was already part of. An alert that keeps firing after its incident was
-- closed doesn't open another one; it has to resolve and fire again.
ALTER TABLE source_events ADD COLUMN IF NOT EXISTS incident_id bigint;
