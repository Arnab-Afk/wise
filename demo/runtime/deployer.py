"""Runs each Shopfront service at a chosen git commit, and keeps the deploy history.

Endpoints: services, deploy, rollback, restart, flags. Every deploy is reported to Tracewise.
"""

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException

REPO = Path(os.environ.get("SHOPFRONT_REPO", "/repos/shopfront"))
WORK = Path(os.environ.get("DEPLOY_DIR", "/tmp/deploys"))
INGEST_URL = os.environ.get("TW_INGEST_URL", "")
INGEST_KEY = os.environ.get("TW_INGEST_KEY", "")
SELF_URL = os.environ.get("DEPLOYER_SELF_URL", "http://127.0.0.1:7000")

app = FastAPI(title="shopfront-deployer")
lock = threading.RLock()
procs: dict[str, subprocess.Popen] = {}
current: dict[str, str] = {}
history: dict[str, list[dict]] = {}
flags: dict = {"bank_mode": "ok", "payments_use_backup": False}


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def ports() -> dict[str, int]:
    return yaml.safe_load(git("show", "HEAD:services.yaml"))["services"]


def checkout_tree(sha: str) -> Path:
    target = WORK / sha
    if not target.exists():
        tmp = WORK / f".{sha}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        archive = subprocess.run(["git", "-C", str(REPO), "archive", sha], check=True,
                                 capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(tmp)], input=archive, check=True)
        tmp.rename(target)
    return target


def stop(service: str) -> None:
    proc = procs.pop(service, None)
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def start(service: str, sha: str) -> None:
    port_map = ports()
    tree = checkout_tree(sha)
    env = {
        **os.environ,
        "TW_SERVICE": service,
        "TW_SHA": sha,
        "DEPLOYER_URL": SELF_URL,
        "PYTHONPATH": str(tree),
        "SHOPFRONT_PORTS": ",".join(f"{k}={v}" for k, v in port_map.items()),
    }
    procs[service] = subprocess.Popen(
        # Only the gateway is published outside the container; everything else stays internal.
        [sys.executable, "-m", "uvicorn", f"services.{service}.app:app",
         "--host", "0.0.0.0" if service == "gateway" else "127.0.0.1",
         "--port", str(port_map[service]), "--log-level", "warning", "--no-access-log"],
        cwd=tree, env=env,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if procs[service].poll() is not None:
            raise HTTPException(500, f"{service} exited during startup at {sha[:8]}")
        try:
            if httpx.get(f"http://127.0.0.1:{port_map[service]}/healthz", timeout=1).is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise HTTPException(500, f"{service} did not become healthy at {sha[:8]}")


def report(service: str, sha: str, prev: str | None, actor: str, reason: str) -> dict:
    author, email, committed_at, subject = git(
        "show", "-s", "--format=%an%x1f%ae%x1f%cI%x1f%s", sha).split("\x1f")
    record = {"service": service, "sha": sha, "prev_sha": prev, "author": author,
              "author_email": email, "committed_at": committed_at, "message": subject,
              "actor": actor, "reason": reason, "deployed_at": time.time()}
    history.setdefault(service, []).append(record)
    if INGEST_URL:
        try:
            httpx.post(f"{INGEST_URL}/v1/ingest/deploys", json=record,
                       headers={"x-ingest-key": INGEST_KEY}, timeout=5)
        except httpx.HTTPError:
            pass
    return record


def deploy(service: str, ref: str, actor: str, reason: str = "") -> dict:
    with lock:
        if service not in ports():
            raise HTTPException(404, f"unknown service {service}")
        sha = git("rev-parse", f"{ref}^{{commit}}")
        prev = current.get(service)
        stop(service)
        try:
            start(service, sha)
        except HTTPException:
            if prev:  # keep the service up on the old version
                stop(service)
                start(service, prev)
            raise
        current[service] = sha
        return report(service, sha, prev, actor, reason)


@app.on_event("startup")
def boot() -> None:
    def run():
        head = git("rev-parse", "HEAD")
        for service in ports():
            try:
                deploy(service, head, "bootstrap", "initial start")
            except HTTPException as exc:
                print(f"boot {service}: {exc.detail}", flush=True)
        threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=run, daemon=True).start()


def watchdog() -> None:
    """Restart a service whose process died, on the same commit."""
    while True:
        time.sleep(3)
        with lock:
            for service, proc in list(procs.items()):
                if proc.poll() is not None and service in current:
                    try:
                        start(service, current[service])
                    except HTTPException:
                        pass


@app.get("/services")
def list_services():
    with lock:
        return [{"service": s, "port": p, "sha": current.get(s),
                 "running": s in procs and procs[s].poll() is None,
                 "pid": procs[s].pid if s in procs else None} for s, p in ports().items()]


@app.get("/deploys")
def deploys(service: str | None = None):
    rows = [r for s, rs in history.items() if service in (None, s) for r in rs]
    return sorted(rows, key=lambda r: r["deployed_at"], reverse=True)


@app.post("/deploy")
def deploy_endpoint(body: dict):
    return deploy(body["service"], body.get("ref", "HEAD"), body.get("actor", "human"),
                  body.get("reason", ""))


@app.post("/rollback")
def rollback(body: dict):
    service = body["service"]
    with lock:
        current_sha = current.get(service)
        previous = next((r["sha"] for r in reversed(history.get(service, []))
                         if r["sha"] != current_sha), None)
        if body.get("to_sha"):
            previous = body["to_sha"]
        if not previous:
            raise HTTPException(409, f"{service} has no earlier deploy to roll back to")
        return deploy(service, previous, body.get("actor", "human"),
                      body.get("reason", "rollback"))


@app.post("/restart")
def restart(body: dict):
    service = body["service"]
    with lock:
        if service not in current:
            raise HTTPException(404, f"{service} is not deployed")
        stop(service)
        start(service, current[service])
    return {"service": service, "sha": current[service], "restarted": True}


@app.get("/flags")
def get_flags():
    return flags


@app.put("/flags")
def set_flags(body: dict):
    flags.update(body)
    return flags
