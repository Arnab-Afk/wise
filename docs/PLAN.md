# Tracewise: neatHack build plan

> Planning notes written Oct 9 (pre-event planning is allowed).
> **No code until Oct 10, 12:30 PM IST.** Submission window: Oct 12, 7:00–11:55 PM IST.

## The idea (unchanged)

An on-call agent that runs without anyone watching. When something breaks in a running
system it works out what broke, what else is affected and why. It then **fixes it
itself** (rollback, mitigation or a tested code fix), **checks that the system has
recovered**, and writes up the incident with the evidence trail. Every past incident
becomes memory for the next one.

neatHack example task this matches: *"Watch a running system… find the cause and take an
action to fix it"*, plus *"Work while things change"*.

What's new compared with the FalkorDB version: the loop closes. The agent acts and
verifies instead of stopping at a recommendation.

## Judging → where the effort goes

| Criterion | Weight | How we score |
|---|---|---|
| Agent capability | 30% | Closed loop: plan → investigate → act → verify → retry with the next hypothesis. Resumable state, guardrails, budgets. A scenario suite that shows it working across different kinds of fault. |
| Use of neatlogs, Entire, cfo.ai | 25% | All three do real work (see below). The demo covers architecture, implementation, runtime, reasoning and result for each. |
| Demo video (≤3 min) | 20% | One scripted incident end to end, then a fast cut through the scenario suite. |
| Building in public | 15% | Posts on X at every milestone (schedule below). |
| Usefulness and originality | 10% | A self-healing on-call agent that cites its evidence and remembers past fixes. |

## How the three required tools are used

**neatlogs (the agent's observability and our dev loop)**
- `neatlogs.init()` at agent start. One trace per incident run, tagged with `incident_id`, `scenario` and `attempt`.
- Spans (`@neatlogs.span`) on every phase (plan, investigate, hypothesize, act, verify) and every tool call. Retries, failures and state changes are recorded.
- Dev loop: run the scenario suite, find failing runs in neatlogs, fix the agent, re-run and compare runs. Before/after screenshots go in `docs/evidence/`.
- Cost per incident (tokens and $) taken from neatlogs feeds the cfo.ai plan.

**Entire (inside the product, and while we build)**
- *Runtime:* the target system's code is a git repo indexed by `entire graph`. The agent's code tools wrap it:
  - `entire graph diff <prev>..<deploy_sha>`: which symbols the bad deploy changed
  - `entire graph impact <symbol>`: what those changes reach (code-level blast radius)
  - `entire graph query "<symptom>"` / `def` / `neighbors`: find the code behind an error
  - Checkpoint lookup on the deploy's commit: *why* the change was made (the agent session behind it)
- *Fix path:* the coding sub-agent writes the fix in a worktree. Entire captures its session as a checkpoint attached to the fix commit, so every automated fix carries its reasoning.
- *Build:* Entire CLI enabled on our own repo from the first commit, so all of our Claude Code sessions become checkpoints. This also helps with the "commits made during the hackathon" check.

**cfo.ai (the business plan)**
- Model pricing (per monitored service per month, with an optional per-auto-resolved-incident tier), costs (LLM cost per incident from neatlogs, infra), revenue ramp and runway.
- Export to `docs/business/cfo-plan.pdf` and summarise it in the README and demo.

## Architecture

```
┌────────────────── demo system ("Shopfront", docker compose) ──────────────────┐
│ gateway → checkout → payments → (bank stub)                                    │
│         → catalog   → inventory          orders → email                        │
│ each service: small FastAPI app, sends logs + request metrics to ingest        │
│ code lives in its own git repo: demo/shopfront (indexed by entire graph)       │
│ deployer: builds and runs a service at a given git SHA, keeps deploy history   │
│ traffic generator + fault injector (scenarios push "bad" commits)             │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                │ HTTP: /ingest/logs, /ingest/metrics, /ingest/deploys
┌───────────────────────────────▼──────────── Tracewise backend (Python) ───────┐
│ api (FastAPI)  REST + SSE stream of incident timelines                         │
│ ingest         → Postgres (logs, metric rollups, deploys, service edges)       │
│ detector       rolling baselines (EWMA + z-score): error rate, p95 latency,    │
│                silence → opens or updates one Incident per problem             │
│ agent worker   picks up open incidents, runs the loop below, every step        │
│                persisted (resumable after a crash), neatlogs-traced            │
│ tools          telemetry · topology · deploys · git/entire-graph · memory ·    │
│                actions (rollback, flag, restart, fix PR) · verify              │
│ coding sub-agent  Claude in a git worktree: write fix → run tests → commit     │
│ memory         resolved incidents (symptoms, cause, fix, outcome) with search  │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                │
                     thin web viewer (day 3): live incident timeline,
                     evidence trail, actions, verification chart
```

**Stack:** Python 3.12 (neatlogs has Python and TypeScript SDKs, not Go), FastAPI,
Postgres 16 (with `pg_trgm` for memory search), Anthropic SDK (Claude) with a manual
tool-use loop for full control of spans and state, Docker Compose. Optional:
Claude Agent SDK for the coding sub-agent.

## The agent loop

```
OPEN → PLAN → INVESTIGATE → HYPOTHESIZE → ACT → VERIFY ─┬─ recovered → RESOLVE → REMEMBER
                    ▲                                    └─ not recovered → next hypothesis
                    └──────────── new evidence / env changed ───────────┘   (max N attempts → ESCALATE)
```

- **Plan:** breaks "restore checkout" into investigation steps, using memory of similar incidents.
- **Investigate:** metrics, logs, service map (blast radius), recent deploys, `entire graph diff/impact` on suspicious deploys.
- **Hypothesize:** ranked causes, each with evidence and confidence.
- **Act:** picks the least risky action that tests the top hypothesis. Order of preference: feature flag or config, rollback, restart, code fix through a PR. Guardrails: action allowlist, one action at a time, no touching services that aren't implicated, cool-down between actions.
- **Verify:** watches the incident's signals for a window against the baseline. Success needs a sustained return to baseline, not one good sample.
- **Recovery:** every tool call has a timeout and retries; step results are persisted, so a killed worker resumes from the last step; actions are idempotent (keyed by incident and step).
- **Budgets:** max steps, tokens and $ per incident. When they run out it escalates with a handover summary.
- **Environment changes:** a new deploy or a new alert arriving mid-run is injected as an event, and the agent re-plans.

## Data model (Postgres)

`services`, `service_edges`, `deploys` (service, sha, prev_sha, at, author),
`log_events`, `metric_points` (1s/10s rollups), `incidents` (status, severity,
services, opened/resolved, summary), `incident_steps` (seq, phase, tool, input,
output, tokens, cost, ts — the persisted state machine), `actions` (kind, target,
idempotency_key, status, result), `memories` (incident_id, symptoms, cause, fix,
outcome, search vector).

## Scenario suite (also our eval harness)

| # | Scenario | Expected agent behaviour |
|---|---|---|
| S1 | Bad config deploy: payments timeout set to 50 ms | Links errors to the deploy, `entire graph diff` shows the config change, rolls back, verifies |
| S2 | Code bug: checkout crashes on a new optional field | Finds the stack trace, uses `entire graph def/impact` to find the code, coding sub-agent writes a fix and test, deploys, verifies |
| S3 | Downstream outage: the bank stub goes down (no deploy) | Does **not** roll back innocent services; turns on the fallback flag; verifies |
| S4 | Things change mid-run: a second unrelated deploy lands during S1 | Re-plans, doesn't blame the new deploy, finishes S1 |
| S5 | Repeat of S1 a day later | Memory recognises it and fixes it in one step |

`scripts/run_scenarios.py` runs them all, records pass/fail, time to recover, steps
and cost, and links the neatlogs trace for each. Results go to `docs/evidence/scenarios.md`.

## 48-hour schedule (IST)

**Before the start (today, Oct 9)**
- [ ] Register on Luma, complete web check-in (AWS credits), join Discord
- [ ] Get neatlogs, cfo.ai and Anthropic keys ready
- [ ] Create a **new empty GitHub repo** (no commits until 12:30 PM tomorrow)
- [ ] Draft X posts and the demo script

**Day 1: Sat Oct 10**
| Time | Work |
|---|---|
| 09:00 | Kickoff call |
| 12:30–14:00 | Repo, Entire CLI enabled, compose (Postgres), FastAPI skeleton, neatlogs init. **Post 1: "starting"** |
| 14:00–19:00 | Shopfront demo services, deployer at a git SHA, traffic generator, ingest |
| 19:00–24:00 | Detector and incidents; agent loop v1 with read-only tools; first traced run in neatlogs. **Post 2: first trace** |

**Day 2: Sun Oct 11**
| Time | Work |
|---|---|
| 09:00–13:00 | Actions (rollback, flag, restart) plus verify; S1 and S3 pass end to end |
| 13:00–17:00 | entire-graph tools and checkpoint lookup; memory (S5). **Post 3: self-healing clip** |
| 17:00–23:00 | Coding sub-agent and fix-PR path (S2); resumable state and budgets; S4 |
| 23:00– | Run the scenario suite, fix failures using neatlogs run comparison. **Post 4: before/after** |

**Day 3: Mon Oct 12**
| Time | Work |
|---|---|
| 09:00–13:00 | Thin web viewer: live timeline, evidence trail, verification chart |
| 13:00–15:00 | cfo.ai plan using real cost-per-incident numbers |
| 15:00–18:00 | README (setup, architecture, tool usage), evidence folder, record and edit the demo video |
| 19:00–23:55 | **Submit on X** (quote the official post); final build-in-public thread |

**Cut line if we fall behind:** drop the web viewer (show neatlogs and the API stream
instead), then S4, then the coding sub-agent (S2). Never drop verify, neatlogs tracing,
Entire or cfo.ai.

## Demo video (≤3 min)

1. 0:00 Problem: it's 2 AM and checkout is down.
2. 0:15 Push the bad deploy; the agent opens the incident by itself.
3. 0:35 Investigation: blast radius, deploy link, `entire graph diff/impact`, checkpoint context.
4. 1:05 Action and verification: rollback, then the error rate returns to baseline; incident resolved and remembered.
5. 1:30 neatlogs: the span tree for that run, plus a failed run vs a fixed run comparison.
6. 2:00 Entire: the fix commit's checkpoint, and our own build checkpoints.
7. 2:20 cfo.ai: pricing, cost per incident and runway.
8. 2:40 Scenario suite results; closing line.
