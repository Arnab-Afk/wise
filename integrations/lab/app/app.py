"""Lab app for connector tests: Prometheus metrics, JSON logs (stdout + file), OTel traces.

`orders` calls `stock`. GET /fault?on=1 on stock makes it fail half its requests with a stack trace.
"""
import json
import os
import random
import sys
import threading
import time
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram, start_http_server

SERVICE = os.environ["SERVICE"]
DOWNSTREAM = os.environ.get("DOWNSTREAM")
REQS = Counter("http_requests_total", "Requests", ["service", "status"])
LAT = Histogram("http_request_duration_seconds", "Latency", ["service"],
                buckets=(.005, .01, .025, .05, .1, .25, .5, 1, 2.5))
FAULT = {"on": False}
LOG = open(f"/logs/{SERVICE}.log", "a", buffering=1)

provider = TracerProvider(resource=Resource.create({"service.name": f"otel-{SERVICE}", "service.version": "v1.4.2"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="http://lab-otelcol:4318/v1/traces")))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("lab")


def log(level, message, **fields):
    line = json.dumps({"timestamp": time.time(), "level": level, "service": SERVICE, "message": message, **fields})
    print(line, flush=True)
    LOG.write(line + "\n")


def reserve(sku):
    stock = {"apple": 3, "pear": 0}
    if FAULT["on"] and random.random() < 0.5:
        return stock[sku.upper()]  # the "bug": a refactor upper-cased the key
    return stock.get(sku, 0)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/fault"):
            FAULT["on"] = "on=1" in self.path
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(FAULT).encode())
            return
        started, status = time.perf_counter(), 200
        with tracer.start_as_current_span(f"GET {self.path}", kind=trace.SpanKind.SERVER) as span:
            try:
                if DOWNSTREAM:
                    with tracer.start_as_current_span("GET stock", kind=trace.SpanKind.CLIENT,
                                                      attributes={"peer.service": "otel-lab-stock"}):
                        urllib.request.urlopen(f"http://{DOWNSTREAM}/reserve", timeout=2).read()
                else:
                    reserve("apple")
            except Exception as exc:
                status = 502 if DOWNSTREAM else 500
                span.record_exception(exc)
                span.set_status(trace.Status(trace.StatusCode.ERROR))
                log("error", f"{type(exc).__name__}: {exc}", route=self.path, status=status,
                    stack=traceback.format_exc())
            span.set_attribute("http.response.status_code", status)
        REQS.labels(SERVICE, str(status)).inc()
        LAT.labels(SERVICE).observe(time.perf_counter() - started)
        self.send_response(status); self.end_headers(); self.wfile.write(b"{}")


def traffic():
    while True:
        try:
            urllib.request.urlopen("http://127.0.0.1:8080/order", timeout=3).read()
        except Exception:
            pass
        time.sleep(0.1)


if __name__ == "__main__":
    start_http_server(9100)
    if DOWNSTREAM:
        threading.Thread(target=traffic, daemon=True).start()
    log("info", f"{SERVICE} started")
    ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
