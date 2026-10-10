"""neatlogs tracing. Every incident run is one trace; every tool call is a span.

Without NEATLOGS_API_KEY all of this is a no-op, so the agent still runs locally.
"""

import contextlib
import functools

from . import config

enabled = False
try:
    import neatlogs
except ImportError:  # pragma: no cover
    neatlogs = None


def init() -> None:
    global enabled
    if neatlogs and config.NEATLOGS_API_KEY:
        neatlogs.init(api_key=config.NEATLOGS_API_KEY, workflow_name="tracewise-oncall",
                      instrumentations=["anthropic"], tags=["tracewise"], capture_logs=True)
        enabled = True


def incident_trace(incident: dict, attempt: int):
    if not enabled:
        return contextlib.nullcontext()
    return neatlogs.trace(
        f"incident-{incident['id']}", kind="WORKFLOW", session_id=f"incident-{incident['id']}",
        incident_id=str(incident["id"]), incident_title=incident["title"],
        services=",".join(incident["services"]), scenario=incident.get("scenario") or "live",
        attempt=str(attempt))


def traced(kind: str, name: str):
    """Wrap a callable in a neatlogs span when tracing is on."""
    def wrap(fn):
        if not enabled:
            return fn
        return functools.wraps(fn)(neatlogs.span(kind=kind, name=name, tool_name=name
                                                 if kind == "TOOL" else None)(fn))
    return wrap


def flush() -> None:
    if enabled:
        neatlogs.flush()
