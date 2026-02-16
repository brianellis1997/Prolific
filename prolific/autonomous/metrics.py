"""Read/write pipeline run metrics to JSON."""

import json
import os
from datetime import datetime
from pathlib import Path


METRICS_FILE = "blog/data/metrics.json"


def get_metrics_path(project_root: Path) -> Path:
    return project_root / METRICS_FILE


def load_metrics(project_root: Path) -> dict:
    path = get_metrics_path(project_root)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"runs": []}


def save_metrics(project_root: Path, metrics: dict):
    path = get_metrics_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def get_langsmith_url(thread_id: str) -> str | None:
    if os.environ.get("LANGCHAIN_TRACING_V2") != "true":
        return None
    project_name = os.environ.get("LANGCHAIN_PROJECT", "prolific-autonomous")
    try:
        from langsmith import Client
        client = Client()
        project = client.read_project(project_name=project_name)
        return project.url
    except Exception:
        return None


def build_run_record(
    start_time: datetime,
    end_time: datetime,
    status: str,
    topic: str | None = None,
    slug: str | None = None,
    rationale: str | None = None,
    builds_on: str | None = None,
    final_state: dict | None = None,
    costs: dict | None = None,
    thread_id: str | None = None,
    error: str | None = None,
    traceback: str | None = None,
    presentation_result=None,
) -> dict:
    duration = (end_time - start_time).total_seconds()

    word_count = 0
    chapter_count = 0
    source_count = 0
    claim_count = 0
    image_count = 0
    if final_state:
        draft_chunks = final_state.get("draft_chunks", [])
        word_count = sum(getattr(c, "word_count", 0) for c in draft_chunks)
        chapter_count = len(draft_chunks)
        source_count = len(final_state.get("approved_sources", []))
        claim_count = len(final_state.get("claims", []))
        image_count = len(final_state.get("visual_assets", []))

    pptx_metrics = None
    if presentation_result is not None:
        pptx_metrics = presentation_result.to_dict()

    return {
        "date": start_time.strftime("%Y-%m-%d"),
        "timestamp": start_time.isoformat() + "Z",
        "status": status,
        "topic": topic,
        "slug": slug,
        "rationale": rationale,
        "builds_on": builds_on,
        "duration_seconds": int(duration),
        "word_count": word_count,
        "chapter_count": chapter_count,
        "source_count": source_count,
        "claim_count": claim_count,
        "image_count": image_count,
        "costs": costs or {},
        "langsmith_url": get_langsmith_url(thread_id) if thread_id else None,
        "error": error,
        "traceback": traceback,
        "presentation": pptx_metrics,
    }
