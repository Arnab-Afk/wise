"""Runs coding agents (Claude or Cursor, on the team's connected account) to write fixes.

Each fix job gets its own git worktree and branch. The agent works with a minimal environment:
only its own API key and a throwaway home directory, never Tracewise's secrets. Afterwards the
runner checks the result itself: it runs the test suite and records the diff, the commit and the
Entire checkpoint that captured the agent's session.
"""

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import anthropic

from . import config, db, secrets

log = logging.getLogger("tracewise.runner")
WORK = Path(os.environ.get("RUNNER_WORK_DIR", "/work"))
REPO = config.SHOPFRONT_REPO
JOB_TIMEOUT = int(os.environ.get("TW_FIX_TIMEOUT_SECONDS", "900"))
WORKER_ID = f"runner-{socket.gethostname()}"

CLAUDE_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep",
                "Bash(python -m pytest *)", "Bash(python -m py_compile *)",
                "Bash(git status *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git show *)",
                "Bash(git add *)", "Bash(git commit *)", "Bash(entire graph *)"]

PROMPT = """You're fixing a production bug in Shopfront, the repository in your working directory.

Incident: {task}
Service: {service}
You're on branch {branch}, created from commit {base}. Production has already been stabilised
(the bad deploy was rolled back), so take the time to do this properly.

1. Find the code involved. Entire Graph is installed and is the fastest way in:
   entire graph search --query "<what you're looking for>" --repo . --format agent
   entire graph impact --symbol <name> --repo .
2. Make the smallest change that fixes the bug while keeping the feature the change intended.
3. Add a regression test under tests/ that fails without your fix.
4. Run: python -m pytest -q   (it must pass)
5. Commit your changes with a message that starts with "Fix:" and says what caused the bug and how
   you fixed it. Don't touch unrelated files.

Finish with a two-sentence summary of the cause and the fix."""


# ---------- connections ----------

def test_connections() -> None:
    for c in db.query("SELECT id, provider, credential, model FROM connections WHERE status = 'testing'"):
        try:
            key = secrets.decrypt(c["credential"])
            if c["provider"] == "claude":
                anthropic.Anthropic(api_key=key, max_retries=1).models.retrieve(
                    c["model"] or "claude-opus-5-5")
                ok, detail = True, f"Key works; model {c['model']} is available"
            else:
                proc = subprocess.run(["agent", "--list-models", "--api-key", key],
                                      capture_output=True, text=True, timeout=60,
                                      env=agent_env(WORK / "probe", {}))
                ok = proc.returncode == 0 and "not logged in" not in proc.stdout.lower()
                detail = "Key works" if ok else re.sub(r"\x1b\[[0-9;]*m", "",
                                                       (proc.stderr or proc.stdout)).strip()[:300]
        except anthropic.AuthenticationError:
            ok, detail = False, "Anthropic rejected the key"
        except anthropic.NotFoundError:
            ok, detail = False, f"Key works, but model {c['model']} isn't available to it"
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"[:300]
        db.query("UPDATE connections SET status = %s, status_detail = %s WHERE id = %s",
                 "ok" if ok else "failed", detail, c["id"])


# ---------- jobs ----------

def claim() -> dict | None:
    return db.one(
        """UPDATE fix_jobs SET status = 'running', started_at = coalesce(started_at, now()),
                  lease_until = now() + make_interval(secs => %s)
           WHERE id = (SELECT id FROM fix_jobs
                       WHERE status = 'queued' OR (status = 'running' AND lease_until < now())
                       ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING *""", JOB_TIMEOUT + 120)


def append_log(job_id: int, line: str) -> None:
    db.query("UPDATE fix_jobs SET log = log || %s WHERE id = %s", line.rstrip() + "\n", job_id)
    db.notify("incident_events", {"type": "fix_job", "job_id": job_id, "line": line[:300]})


def git(*args: str, cwd: str = REPO, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()[:500]}")
    return proc.stdout.strip()


def agent_env(home: Path, extra: dict) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    return {"PATH": os.environ["PATH"], "HOME": str(home), "LANG": "C.UTF-8",
            "CLAUDE_CONFIG_DIR": str(home / ".claude"), "PYTHONDONTWRITEBYTECODE": "1", **extra}


def run_agent(job: dict, conn: dict, workdir: Path) -> tuple[str, float | None]:
    """Run the connected agent in the worktree. Returns (final summary, cost)."""
    key = secrets.decrypt(conn["credential"])
    label = "Claude Agent" if conn["provider"] == "claude" else "Cursor Agent"
    env = agent_env(WORK / f"home-{job['id']}", {
        "GIT_AUTHOR_NAME": f"Tracewise ({label})", "GIT_AUTHOR_EMAIL": "agent@tracewise.dev",
        "GIT_COMMITTER_NAME": f"Tracewise ({label})", "GIT_COMMITTER_EMAIL": "agent@tracewise.dev",
        "PYTHONPATH": str(workdir)})
    prompt = PROMPT.format(task=job["task"], service=job["service"], branch=job["branch"],
                           base=job["base_sha"][:10])
    if conn["provider"] == "claude":
        env["ANTHROPIC_API_KEY"] = key
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--permission-mode", "acceptEdits", "--permission-prompts", "none",
               "--allowedTools", *CLAUDE_TOOLS, "--max-budget-usd", "3"]
        if conn["model"]:
            cmd += ["--model", conn["model"]]
    else:
        env["CURSOR_API_KEY"] = key
        cmd = ["agent", "-p", prompt, "--output-format", "stream-json", "--force", "--trust"]
        if conn["model"]:
            cmd += ["--model", conn["model"]]

    proc = subprocess.Popen(cmd, cwd=workdir, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    killer = threading.Timer(JOB_TIMEOUT, proc.kill)
    killer.start()
    summary, cost = "", None
    try:
        for line in proc.stdout:
            event = parse(line)
            if event is None:
                continue
            for text in describe(event):
                append_log(job["id"], text)
            if event.get("type") == "result":
                result = event.get("result")
                summary = result if isinstance(result, str) and result else summary
                cost = event.get("total_cost_usd", cost)
    finally:
        killer.cancel()
        proc.wait()
    if proc.returncode != 0 and not summary:
        raise RuntimeError(f"{label} exited with code {proc.returncode}")
    return summary, cost


def parse(line: str) -> dict | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        event = None
    if isinstance(event, dict):
        return event
    return {"type": "raw", "text": line.strip()} if line.strip() else None


def describe(event: dict) -> list[str]:
    """Short, human-readable progress lines from either agent's stream-json events."""
    try:
        return _describe(event)
    except Exception:  # progress lines are best-effort; never fail a job over one
        return []


def _describe(event: dict) -> list[str]:
    out = []
    if event.get("type") == "raw":
        out.append(event["text"][:300])
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            inp = block.get("input") if isinstance(block.get("input"), dict) else {}
            detail = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
            out.append(f"→ {block.get('name')}: {str(detail)[:200]}")
        elif block.get("type") == "text" and event.get("type") == "assistant" and block.get("text"):
            out.append(block["text"].strip().splitlines()[0][:200])
    if event.get("type") == "tool_call" and event.get("subtype") == "started":
        out.append(f"→ {json.dumps(event.get('tool_call'))[:200]}")
    return out


def run_job(job: dict) -> None:
    conn = db.one("SELECT * FROM connections WHERE id = %s", job["connection_id"])
    workdir = WORK / f"fix-{job['id']}"
    shutil.rmtree(workdir, ignore_errors=True)
    git("worktree", "prune")
    git("worktree", "add", "-B", job["branch"], str(workdir), job["base_sha"])
    append_log(job["id"], f"Worktree ready on {job['branch']} from {job['base_sha'][:10]}")
    try:
        summary, cost = run_agent(job, conn, workdir)
        db.query("UPDATE connections SET last_used_at = now() WHERE id = %s", conn["id"])
        commits = git("log", "--format=%H", f"{job['base_sha']}..HEAD", cwd=str(workdir)).split()
        if not commits:
            raise RuntimeError("The agent didn't commit a fix.")
        head = commits[0]
        message = git("log", "-1", "--format=%B", head, cwd=str(workdir))
        checkpoint = next((l.split(":", 1)[1].strip() for l in message.splitlines()
                           if l.lower().startswith("entire-checkpoint:")), None)
        # Check the agent's work ourselves rather than trusting its summary.
        tests = subprocess.run(["python", "-m", "pytest", "-q"], cwd=workdir, capture_output=True,
                               text=True, timeout=300, env={**agent_env(WORK / "probe", {}),
                                                            "PYTHONPATH": str(workdir)})
        passed = tests.returncode == 0
        append_log(job["id"], f"Runner ran the tests: {'passed' if passed else 'FAILED'}")
        db.query(
            "UPDATE fix_jobs SET status = %s, commit_sha = %s, checkpoint_id = %s, tests_passed = %s,"
            " test_output = %s, diff = %s, agent_summary = %s, cost_usd = %s, finished_at = now()"
            " WHERE id = %s",
            "ready" if passed else "failed", head, checkpoint, passed,
            (tests.stdout + tests.stderr)[-4000:], git("diff", f"{job['base_sha']}..{head}",
                                                       cwd=str(workdir))[:20000],
            summary[:4000], cost, job["id"])
    except Exception as exc:
        log.exception("fix job %s failed", job["id"])
        append_log(job["id"], f"Failed: {exc}")
        db.query("UPDATE fix_jobs SET status = 'failed', error = %s, finished_at = now() WHERE id = %s",
                 str(exc)[:2000], job["id"])
    finally:
        git("worktree", "remove", "--force", str(workdir), check=False)
        shutil.rmtree(WORK / f"home-{job['id']}", ignore_errors=True)
        db.notify("incident_events", {"type": "fix_job_done", "job_id": job["id"]})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    db.open_pool()
    WORK.mkdir(parents=True, exist_ok=True)
    log.info("runner %s up", WORKER_ID)
    while True:
        try:
            test_connections()
            job = claim()
            if job:
                log.info("fix job %s: %s via %s", job["id"], job["service"], job["provider"])
                run_job(job)
                continue
        except Exception:
            log.exception("runner loop error")
        time.sleep(2)


if __name__ == "__main__":
    main()
