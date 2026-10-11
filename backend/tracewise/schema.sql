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

-- ---------- accounts, workspaces and email ----------

CREATE TABLE IF NOT EXISTS users (
    id               bigserial PRIMARY KEY,
    email            text NOT NULL UNIQUE,
    name             text,
    avatar_url       text,
    notify_incidents text NOT NULL DEFAULT 'escalations',  -- all | escalations | none
    created_at       timestamptz NOT NULL DEFAULT now(),
    last_login_at    timestamptz
);

-- Google / GitHub accounts linked to a user.
CREATE TABLE IF NOT EXISTS auth_identities (
    provider         text NOT NULL,
    provider_user_id text NOT NULL,
    user_id          bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, provider_user_id)
);

-- One-time sign-in codes. Only a hash is stored.
CREATE TABLE IF NOT EXISTS otp_codes (
    id          bigserial PRIMARY KEY,
    email       text NOT NULL,
    code_hash   text NOT NULL,
    attempts    int NOT NULL DEFAULT 0,
    ip          text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    consumed_at timestamptz
);
CREATE INDEX IF NOT EXISTS otp_codes_email ON otp_codes (email, created_at DESC);

CREATE TABLE IF NOT EXISTS sessions (
    id           bigserial PRIMARY KEY,
    token_hash   text NOT NULL UNIQUE,
    user_id      bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    method       text NOT NULL,          -- email | google | github
    ip           text,
    user_agent   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz
);

CREATE TABLE IF NOT EXISTS workspaces (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,
    slug        text NOT NULL UNIQUE,
    created_by  bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id bigint NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id      bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role         text NOT NULL,          -- owner | admin | member | viewer
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS invites (
    id           bigserial PRIMARY KEY,
    workspace_id bigint NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email        text NOT NULL,
    role         text NOT NULL,
    token_hash   text NOT NULL UNIQUE,
    invited_by   bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    accepted_at  timestamptz,
    revoked_at   timestamptz
);

-- A system the agent looks after (Shopfront is the first one).
CREATE TABLE IF NOT EXISTS projects (
    id           bigserial PRIMARY KEY,
    workspace_id bigint NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         text NOT NULL,
    slug         text NOT NULL,
    description  text,
    created_by   bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, slug)
);

-- Every email Tracewise sends (or would send without SMTP), rendered, for audit and preview.
CREATE TABLE IF NOT EXISTS email_log (
    id          bigserial PRIMARY KEY,
    to_email    text NOT NULL,
    template    text NOT NULL,
    subject     text NOT NULL,
    text_body   text NOT NULL,
    html_body   text NOT NULL,
    status      text NOT NULL,           -- queued | sent | failed | skipped
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    sent_at     timestamptz
);
CREATE INDEX IF NOT EXISTS email_log_created ON email_log (created_at DESC);

-- ---------- multi-tenancy: every piece of telemetry and every incident belongs to a project ----------

ALTER TABLE projects ADD COLUMN IF NOT EXISTS deployer_url text;  -- set when Tracewise can deploy/roll back
ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_path text;     -- set when the code is checked out for the agent

-- Keys that send telemetry into one project. Only a hash is stored; the key is shown once.
CREATE TABLE IF NOT EXISTS project_keys (
    id           bigserial PRIMARY KEY,
    project_id   bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name         text NOT NULL,
    prefix       text NOT NULL,          -- first characters, to tell keys apart
    key_hash     text NOT NULL UNIQUE,
    created_by   bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    revoked_at   timestamptz
);

ALTER TABLE services       ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE service_edges  ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE metric_points  ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE edge_points    ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE log_events     ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE deploys        ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE incidents      ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE memories       ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE scenario_runs  ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE fix_jobs       ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE sources        ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
ALTER TABLE source_events  ADD COLUMN IF NOT EXISTS project_id bigint REFERENCES projects(id) ON DELETE CASCADE;
-- Coding-agent accounts belong to the team (workspace), shared by its projects.
ALTER TABLE connections    ADD COLUMN IF NOT EXISTS workspace_id bigint REFERENCES workspaces(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS metric_points_project ON metric_points (project_id, service, ts DESC);
CREATE INDEX IF NOT EXISTS log_events_project ON log_events (project_id, ts DESC);
CREATE INDEX IF NOT EXISTS edge_points_project ON edge_points (project_id, ts DESC);
CREATE INDEX IF NOT EXISTS deploys_project ON deploys (project_id, deployed_at DESC);
CREATE INDEX IF NOT EXISTS incidents_project ON incidents (project_id, id DESC);
CREATE INDEX IF NOT EXISTS source_events_project ON source_events (project_id, active_until DESC);

-- ---------- teams: groups of members that own projects ----------

ALTER TABLE projects ADD COLUMN IF NOT EXISTS stack text[] NOT NULL DEFAULT '{}';  -- what it runs on

CREATE TABLE IF NOT EXISTS teams (
    id           bigserial PRIMARY KEY,
    workspace_id bigint NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         text NOT NULL,
    description  text,
    created_by   bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, name)
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id    bigint NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id    bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id)
);

-- Which team is on call for a project: its members get that project's incident emails.
CREATE TABLE IF NOT EXISTS team_projects (
    team_id    bigint NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    project_id bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (team_id, project_id)
);

-- ---------- Slack app ----------

-- One Slack workspace connected per Tracewise workspace. The bot token is encrypted.
CREATE TABLE IF NOT EXISTS slack_installations (
    id            bigserial PRIMARY KEY,
    workspace_id  bigint NOT NULL UNIQUE REFERENCES workspaces(id) ON DELETE CASCADE,
    team_id       text NOT NULL,
    team_name     text,
    bot_user_id   text,
    bot_token     bytea NOT NULL,
    scope         text,
    installed_by  bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS slack_installations_team ON slack_installations (team_id);

-- Which channel a project's incidents go to, and which events.
CREATE TABLE IF NOT EXISTS slack_routes (
    project_id   bigint PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    channel_id   text NOT NULL,
    channel_name text,
    events       text[] NOT NULL DEFAULT '{opened,action,fix,resolved,escalated}',
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Each incident is one Slack thread: the root message is updated as its status changes.
CREATE TABLE IF NOT EXISTS slack_threads (
    incident_id bigint PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE,
    channel_id  text NOT NULL,
    ts          text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Timeline steps already posted (so a restart never double-posts), and where the poster got to.
CREATE TABLE IF NOT EXISTS slack_posts (
    step_id   bigint PRIMARY KEY,
    posted_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS slack_cursor (
    id      int PRIMARY KEY DEFAULT 1,
    step_id bigint NOT NULL
);

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS acknowledged_by text;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS acknowledged_at timestamptz;
