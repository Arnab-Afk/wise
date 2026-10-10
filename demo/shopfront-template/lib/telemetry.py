"""Request metrics, error logs and dependency calls, shipped to Tracewise every 2s."""

import os
import threading
import time
import traceback

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

SERVICE = os.environ.get("TW_SERVICE", "unknown")
SHA = os.environ.get("TW_SHA", "")
INGEST_URL = os.environ.get("TW_INGEST_URL", "")
INGEST_KEY = os.environ.get("TW_INGEST_KEY", "")
PORTS = dict(
    item.split("=") for item in os.environ.get("SHOPFRONT_PORTS", "").split(",") if item
)

_lock = threading.Lock()
_latencies: list[float] = []
_errors = 0
_logs: list[dict] = []
_edges: dict[str, dict] = {}


class DependencyError(Exception):
    def __init__(self, target: str, detail: str):
        super().__init__(f"call to {target} failed: {detail}")
        self.target = target


def _record(latency_ms: float, ok: bool) -> None:
    global _errors
    with _lock:
        _latencies.append(latency_ms)
        if not ok:
            _errors += 1


def log(level: str, message: str, **fields) -> None:
    with _lock:
        if len(_logs) < 200:
            _logs.append({"ts": time.time(), "level": level, "message": message[:2000], **fields})


def call(target: str, method: str, path: str, json=None, timeout: float = 2.0):
    """Call another Shopfront service and record the edge."""
    started = time.perf_counter()
    ok = False
    try:
        resp = httpx.request(
            method, f"http://127.0.0.1:{PORTS[target]}{path}", json=json, timeout=timeout
        )
        ok = resp.status_code < 500
        if not ok:
            raise DependencyError(target, f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()
    except httpx.TimeoutException:
        raise DependencyError(target, f"timed out after {int(timeout * 1000)}ms")
    except httpx.HTTPError as exc:
        raise DependencyError(target, f"{type(exc).__name__}: {exc}")
    finally:
        latency = (time.perf_counter() - started) * 1000
        with _lock:
            edge = _edges.setdefault(target, {"calls": 0, "errors": 0, "latency_ms": 0.0})
            edge["calls"] += 1
            edge["errors"] += 0 if ok else 1
            edge["latency_ms"] += latency


def _flush_loop() -> None:
    global _errors, _latencies, _logs, _edges
    client = httpx.Client(timeout=3.0)
    while True:
        time.sleep(2.0)
        with _lock:
            lat, errs, logs, edges = _latencies, _errors, _logs, _edges
            _latencies, _errors, _logs, _edges = [], 0, [], {}
        lat.sort()

        def pct(p: float) -> float:
            return round(lat[min(len(lat) - 1, int(len(lat) * p))], 1) if lat else 0.0

        body = {
            "service": SERVICE,
            "sha": SHA,
            "ts": time.time(),
            "count": len(lat),
            "errors": errs,
            "p50_ms": pct(0.5),
            "p95_ms": pct(0.95),
            "max_ms": round(lat[-1], 1) if lat else 0.0,
            "logs": logs,
            "edges": [{"to": k, **v} for k, v in edges.items()],
        }
        if not INGEST_URL:
            continue
        try:
            client.post(f"{INGEST_URL}/v1/ingest/telemetry", json=body,
                        headers={"x-ingest-key": INGEST_KEY})
        except httpx.HTTPError:
            pass


def instrument(app: FastAPI) -> None:
    threading.Thread(target=_flush_loop, daemon=True).start()

    @app.middleware("http")
    async def _measure(request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except DependencyError as exc:
            _record((time.perf_counter() - started) * 1000, False)
            log("error", str(exc), route=request.url.path, status=502, dependency=exc.target)
            return JSONResponse({"error": str(exc)}, status_code=502)
        except Exception as exc:
            _record((time.perf_counter() - started) * 1000, False)
            log("error", f"{type(exc).__name__}: {exc}", route=request.url.path, status=500,
                trace=traceback.format_exc()[-3000:])
            return JSONResponse({"error": "internal error"}, status_code=500)
        _record((time.perf_counter() - started) * 1000, response.status_code < 500)
        return response

    @app.get("/healthz")
    def healthz():
        return {"service": SERVICE, "sha": SHA}
