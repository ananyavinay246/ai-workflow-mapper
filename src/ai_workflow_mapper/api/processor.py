"""Stub job processor — seam for the real workflow analysis pipeline."""

from typing import Any

from .models import JobInput


def process(job_input: JobInput) -> dict[str, Any]:
    """Process a workflow mapper job and return the result dict.

    This is a stub. Wire up document_loader → llm_adapter → report_renderer here
    in the next implementation slice.
    """
    documents = job_input.input.get("documents", [])
    return {
        "summary": "Analysis stub — workflow pipeline not yet wired",
        "documents_processed": len(documents),
    }
