"""Self-contained JSON schemas for LLM analysis enrichment (thorough mode)."""

from __future__ import annotations

import json
from pathlib import Path

_SCHEMAS_DIR = Path(__file__).parents[3] / "schemas"


def load_enrichment_schema(*, array_property: str, finding_def: str) -> dict:
    """Return a narrow output schema with ``$defs/evidence`` for nested ``$ref`` resolution."""
    schema = json.loads(
        (_SCHEMAS_DIR / "analysis_findings.schema.json").read_text(encoding="utf-8")
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [array_property],
        "$defs": {
            "evidence": schema["$defs"]["evidence"],
        },
        "properties": {
            array_property: {
                "type": "array",
                "items": schema["$defs"][finding_def],
            }
        },
    }
