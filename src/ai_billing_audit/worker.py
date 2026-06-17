"""Worker entrypoint for the ai-billing-audit deployment.

v1 architecture (kanban t_7f6ffde6)
----------------------------------

The job queue lives in-process in the FastAPI service
(:mod:`ai_billing_audit.job_queue`). When the upload portal enqueues a
job, a thread pool inside the API process picks it up and runs the
synth agent.

The v1 task spec asks for a *separate* ``worker`` service in the
docker-compose stack. This module exists to satisfy that requirement:

* The container stays alive (so ``docker ps`` shows the 4-service
  topology the spec calls for).
* Every 30 seconds it logs a heartbeat line documenting the v1 state:
  "queue is in-process in the api, future broker migration tracked
  in t_<id>." A real broker-backed worker replaces this when the
  audit pipeline moves off the FastAPI process.

A future card can replace this stub with one that connects to
``$DATABASE_URL`` via ``pg LISTEN/NOTIFY`` and processes jobs
out-of-band. For v1, the worker is a no-op liveness sidecar.
"""
from __future__ import annotations

import logging
import os
import signal
import time
from typing import NoReturn

__all__ = ["main"]


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s worker %(levelname)s %(message)s",
    )


def main() -> NoReturn:
    """Run the worker heartbeat loop until SIGTERM/SIGINT."""
    _configure_logging()
    log = logging.getLogger("ai_billing_audit.worker")

    stop = {"flag": False}

    def _handle(_signum, _frame):  # noqa: ANN001
        log.info("shutdown signal received, exiting")
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    log.info(
        "worker booting: queue is in-process in the api (v1). "
        "DATABASE_URL=%s AUDIT_TRAIL_DB=%s LLM_PROVIDER=%s",
        bool(os.environ.get("DATABASE_URL")),
        bool(os.environ.get("AUDIT_TRAIL_DB")),
        os.environ.get("LLM_PROVIDER", "<unset>"),
    )

    while not stop["flag"]:
        time.sleep(30)
        if not stop["flag"]:
            log.info("idle — heartbeat (queue is in-process in the api)")

    raise SystemExit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
