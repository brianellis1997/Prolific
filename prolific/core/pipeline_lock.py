"""Pipeline lock — tracks which pipelines are actively running.

Used by /health endpoint to report if it's safe to deploy.
Any deploy while a pipeline is running will kill the process and waste money.
"""

import logging
import threading
from datetime import datetime, UTC

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_active: dict[str, dict] = {}


def acquire_pipeline(name: str, topic: str = "") -> str:
    """Mark a pipeline as actively running. Returns a run_id."""
    import uuid
    run_id = str(uuid.uuid4())[:8]
    with _lock:
        _active[run_id] = {
            "name": name,
            "topic": topic,
            "started_at": datetime.now(UTC).isoformat(),
        }
    logger.info(f"Pipeline started: {name} (run_id={run_id}, topic={topic})")
    return run_id


def release_pipeline(run_id: str) -> None:
    """Mark a pipeline as finished."""
    with _lock:
        info = _active.pop(run_id, None)
    if info:
        logger.info(f"Pipeline finished: {info['name']} (run_id={run_id})")


def get_active_pipelines() -> list[dict]:
    """Get list of currently running pipelines."""
    with _lock:
        return [{"run_id": k, **v} for k, v in _active.items()]
