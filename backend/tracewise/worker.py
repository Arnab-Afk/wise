"""Background worker: runs the detector and hands open incidents to the agent.

Incidents are claimed with a lease that the agent renews as it works. If a worker dies, the
lease runs out and any worker picks the incident up again from its saved conversation.
"""

import logging
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, db, detector, tracing
from .agent import loop

log = logging.getLogger("tracewise.worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
MAX_PARALLEL = 3


def detector_loop() -> None:
    while True:
        try:
            detector.tick()
        except Exception:
            log.exception("detector tick failed")
        time.sleep(5)


def claim() -> int | None:
    row = db.one(
        """UPDATE incidents SET lease_owner = %s, lease_until = now() + make_interval(secs => %s)
           WHERE id = (SELECT id FROM incidents
                       WHERE status IN ('open', 'investigating', 'acting', 'fixing', 'verifying')
                         AND (lease_until IS NULL OR lease_until < now())
                       ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING id""", WORKER_ID, config.LEASE_SECONDS)
    return row["id"] if row else None


def work(incident_id: int) -> None:
    try:
        loop.run_incident(incident_id, WORKER_ID)
    except Exception:
        log.exception("incident %s run failed; it will be resumed when the lease expires", incident_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    db.open_pool()
    tracing.init()
    log.info("worker %s up (agent %s, neatlogs %s, model %s)", WORKER_ID,
             "on" if config.AGENT_ENABLED else "off", "on" if tracing.enabled else "off", config.MODEL)
    threading.Thread(target=detector_loop, daemon=True).start()
    from . import slack
    slack.start_notifier()
    running: dict[int, object] = {}
    with ThreadPoolExecutor(MAX_PARALLEL) as pool:
        while True:
            running = {i: f for i, f in running.items() if not f.done()}
            if config.AGENT_ENABLED and len(running) < MAX_PARALLEL:
                incident_id = claim()
                if incident_id and incident_id not in running:
                    log.info("claimed incident %s", incident_id)
                    running[incident_id] = pool.submit(work, incident_id)
                    continue
            time.sleep(2)


if __name__ == "__main__":
    main()
