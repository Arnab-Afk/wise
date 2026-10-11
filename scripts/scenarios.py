#!/usr/bin/env python3
"""Break Shopfront on purpose, then measure whether Tracewise fixes it on its own.

    scripts/scenarios.py list
    scripts/scenarios.py run bad-config [--no-wait]
    scripts/scenarios.py run all
    scripts/scenarios.py reset

Each run is recorded through the Tracewise API, the detector tags the incident it opens with the
scenario name, and the result (recovered or not, time to recover, turns, cost) is written back.
Results are appended to docs/evidence/scenarios.md.
"""

import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT / "demo" / "shopfront"
API = "http://localhost:19100"
DEPLOYER = "http://localhost:19102"
EVIDENCE = ROOT / "docs" / "evidence" / "scenarios.md"
BASELINE_TAG = "baseline"


def ingest_key() -> str:
    """The API needs a session or the ingest key; scripts use the key from .env."""
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("TW_INGEST_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def http(method: str, url: str, body: dict | None = None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"content-type": "application/json", "x-ingest-key": ingest_key()})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read() or "null")


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(author: str, email: str, message: str, edits: dict[str, tuple[str, str]]) -> str:
    """Apply text replacements {path: (old, new)} and commit them as `author`."""
    for path, (old, new) in edits.items():
        f = REPO / path
        text = f.read_text()
        if old not in text:
            raise SystemExit(f"{path}: expected text not found; run `reset` first")
        f.write_text(text.replace(old, new, 1))
    git("add", "-A")
    git("-c", f"user.name={author}", "-c", f"user.email={email}", "commit", "-q", "-m", message)
    return git("rev-parse", "HEAD")


def deploy(service: str, actor: str = "ci", reason: str = "") -> dict:
    return http("POST", f"{DEPLOYER}/deploy", {"service": service, "ref": "HEAD", "actor": actor,
                                                "reason": reason})


# ---------- faults ----------

def bad_config() -> None:
    """Payments' bank timeout drops from 800ms to 50ms; most card charges time out."""
    commit("Meera Nair", "meera@shopfront.dev", "Tighten bank timeout so payments fail fast under load",
           {"config/payments.yaml": ("bank_timeout_ms: 800", "bank_timeout_ms: 50")})
    deploy("payments", reason="config change")


def code_bug() -> None:
    """Checkout starts charging for gift wrap but crashes on carts without it."""
    commit("Priya Shah", "priya@shopfront.dev", "Charge for gift wrapping at checkout", {
        "services/checkout/pricing.py": (
            'COUPONS = {"WELCOME10": 0.10, "FALL20": 0.20}',
            'COUPONS = {"WELCOME10": 0.10, "FALL20": 0.20}\nGIFT_WRAP_FEES = {"classic": 4.0, "kraft": 2.5}\n\n\n'
            'def gift_wrap_fee(gift_wrap: dict) -> float:\n    return GIFT_WRAP_FEES[gift_wrap["style"]]'),
        "services/checkout/app.py": (
            '    totals = pricing.compute_total(items, prices, body.get("coupon"), settings["tax_rate"])',
            '    totals = pricing.compute_total(items, prices, body.get("coupon"), settings["tax_rate"])\n'
            '    totals["gift_wrap"] = pricing.gift_wrap_fee(body.get("gift_wrap"))\n'
            '    totals["total"] = round(totals["total"] + totals["gift_wrap"], 2)'),
    })
    deploy("checkout", reason="gift wrap feature")


def bank_outage() -> None:
    """The bank (outside our control) goes down. No deploy is involved."""
    http("PUT", f"{DEPLOYER}/flags", {"bank_mode": "down"})


def unrelated_deploy() -> None:
    commit("Rahul Iyer", "rahul@shopfront.dev", "List products in alphabetical order", {
        "services/catalog/app.py": ("    return list(PRODUCTS.values())",
                                    "    return sorted(PRODUCTS.values(), key=lambda p: p[\"name\"])"),
    })
    deploy("catalog", reason="catalog sort order")


def change_during_incident() -> None:
    """bad-config, then an unrelated catalog deploy lands while the agent is investigating."""
    before = max((i["id"] for i in http("GET", f"{API}/v1/incidents")), default=0)
    bad_config()
    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(2)
        if any(i["id"] > before for i in http("GET", f"{API}/v1/incidents")):
            break
    time.sleep(6)
    unrelated_deploy()


SCENARIOS = {
    "bad-config": (bad_config, "Payments config change makes most card charges time out"),
    "code-bug": (code_bug, "Checkout deploy crashes on carts without gift wrap"),
    "bank-outage": (bank_outage, "The bank is down; nothing was deployed"),
    "change-mid-incident": (change_during_incident, "bad-config, plus an unrelated deploy mid-investigation"),
    "repeat": (bad_config, "bad-config again, to test memory of the first time"),
}


# ---------- reset / run ----------

def reset() -> None:
    """Restore the baseline code, flags and deploys."""
    http("PUT", f"{DEPLOYER}/flags", {"bank_mode": "ok", "payments_use_backup": False})
    try:
        base = git("rev-parse", BASELINE_TAG)
    except subprocess.CalledProcessError:
        base = git("rev-list", "--max-parents=0", "HEAD")  # fallback
    if git("diff", "--stat", base, "HEAD"):
        git("rm", "-rq", "--cached", ".")
        git("checkout", base, "--", ".")
        for path in git("ls-files", "--others", "--exclude-standard").splitlines():
            (REPO / path).unlink()
        git("add", "-A")
        git("-c", "user.name=Shopfront CI", "-c", "user.email=ci@shopfront.dev", "commit", "-q",
            "-m", "Restore baseline after scenario")
    running = {s["service"]: s["sha"] for s in http("GET", f"{DEPLOYER}/services")}
    head = git("rev-parse", "HEAD")
    for service, sha in running.items():
        if not sha or git("diff", "--stat", sha, head, "--", f"services/{service}", "config", "lib"):
            deploy(service, actor="ci", reason="reset to baseline")
    print("reset done")


def wait_healthy(timeout: int = 240) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(s["status"] == "healthy" for s in http("GET", f"{API}/v1/health")):
            return True
        time.sleep(5)
    return False


def run(name: str, wait: bool = True, timeout: int = 900) -> dict:
    fault, description = SCENARIOS[name]
    if not wait_healthy():
        raise SystemExit("Shopfront isn't healthy; run `reset` and wait")
    scenario = http("POST", f"{API}/v1/scenarios", {"name": name})
    started = time.time()
    print(f"▶ {name}: {description}")
    fault()
    if not wait:
        return {}
    incident_id, incident = None, None
    while time.time() - started < timeout:
        time.sleep(5)
        run_row = next(r for r in http("GET", f"{API}/v1/scenarios") if r["id"] == scenario["id"])
        incident_id = run_row["incident_id"]
        if incident_id:
            incident = http("GET", f"{API}/v1/incidents/{incident_id}")
            if incident["status"] in ("resolved", "escalated"):
                break
    result = {
        "scenario": name,
        "incident_id": incident_id,
        "status": incident["status"] if incident else "not detected",
        "detected_after_s": round((datetime.fromisoformat(incident["opened_at"]).timestamp() - started), 1)
        if incident else None,
        "recovered_after_s": round(datetime.fromisoformat(incident["resolved_at"]).timestamp() - started, 1)
        if incident and incident.get("resolved_at") else None,
        "turns": incident.get("turns") if incident else None,
        "cost_usd": float(incident["cost_usd"]) if incident and incident.get("cost_usd") else None,
        "actions": [f"{a['kind']} {a['target']}" for a in incident["actions"] if a["status"] == "done"]
        if incident else [],
        "root_cause": incident.get("root_cause") if incident else None,
    }
    http("PATCH", f"{API}/v1/scenarios/{scenario['id']}", {"result": result})
    record(result)
    print(json.dumps(result, indent=2))
    return result


def record(r: dict) -> None:
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    if not EVIDENCE.exists():
        EVIDENCE.write_text("# Scenario results\n\n| When | Scenario | Incident | Outcome | Detected | "
                            "Recovered | Turns | Cost | Actions |\n|---|---|---|---|---|---|---|---|---|\n")
    with EVIDENCE.open("a") as f:
        f.write(f"| {datetime.now():%b %d %H:%M} | {r['scenario']} | #{r['incident_id']} | {r['status']} | "
                f"{r['detected_after_s']}s | {r['recovered_after_s']}s | {r['turns']} | "
                f"${(r['cost_usd'] or 0):.2f} | {', '.join(r['actions']) or '-'} |\n")


def main(argv: list[str]) -> None:
    if not argv or argv[0] == "list":
        for name, (_, desc) in SCENARIOS.items():
            print(f"{name:22s} {desc}")
    elif argv[0] == "reset":
        reset()
    elif argv[0] == "tag-baseline":
        git("tag", "-f", BASELINE_TAG, "HEAD")
        print("baseline tagged at", git("rev-parse", "--short", "HEAD"))
    elif argv[0] == "run":
        names = list(SCENARIOS) if argv[1] == "all" else [argv[1]]
        for name in names:
            run(name, wait="--no-wait" not in argv)
            if len(names) > 1:
                reset()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
