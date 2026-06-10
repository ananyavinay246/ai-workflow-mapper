"""Validate example fixtures and API payloads against domain JSON schemas."""

import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).parents[2]
SCHEMAS_DIR = ROOT / "schemas"


@pytest.fixture(scope="module")
def schema_store() -> dict:
    store: dict = {}
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        store[data["$id"]] = data
    return store


def validate_against_schema(instance: dict, schema_name: str, schema_store: dict) -> None:
    """Validate instance using a local $id store (no remote $ref fetch)."""
    schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    resolver = jsonschema.RefResolver(base_uri=schema["$id"], referrer=schema, store=schema_store)
    jsonschema.validate(instance, schema, resolver=resolver)


def test_request_example_validates(schema_store):
    data = json.loads((ROOT / "examples" / "request.example.json").read_text(encoding="utf-8"))
    validate_against_schema(data, "input.schema.json", schema_store)


def test_response_example_validates(schema_store):
    data = json.loads((ROOT / "examples" / "response.example.json").read_text(encoding="utf-8"))
    validate_against_schema(data, "output.schema.json", schema_store)


def test_simple_fixture_validates(schema_store):
    data = json.loads(
        (ROOT / "fixtures" / "simple" / "request.example.json").read_text(encoding="utf-8")
    )
    validate_against_schema(data, "input.schema.json", schema_store)


def test_workflow_result_minimal_validates(schema_store):
    data = {
        "normalization_summary": {
            "normalized_documents": 0,
            "skipped_documents": 0,
            "skipped": [],
            "warnings": [],
        }
    }
    validate_against_schema(data, "workflow_result.schema.json", schema_store)


def test_workflow_result_with_bottlenecks_validates(schema_store):
    data = {
        "normalization_summary": {
            "normalized_documents": 1,
            "skipped_documents": 0,
            "skipped": [],
            "warnings": [],
        },
        "analysis": {
            "bottlenecks": [
                {
                    "id": "bn-s2",
                    "name": "Review and approve request",
                    "severity": "Critical",
                    "description": "Approval queue on critical path.",
                    "impact": "Blocks fulfillment.",
                    "root_cause_hypothesis": "Single approver.",
                    "evidence": [
                        {
                            "quote": "Review and approve request",
                            "source_filename": "sop.txt",
                        }
                    ],
                }
            ]
        },
    }
    validate_against_schema(data, "workflow_result.schema.json", schema_store)


def test_process_extraction_empty_validates(schema_store):
    validate_against_schema(
        {"steps": [], "handoffs": [], "warnings": []},
        "process_extraction.schema.json",
        schema_store,
    )
