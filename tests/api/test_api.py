"""API contract tests verifying behavior matches openapi.yaml."""

import json
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from ai_workflow_mapper.api.app import create_app

SCHEMAS_DIR = Path(__file__).parents[2] / "schemas"

_VALID_BODY = {
    "request_id": "req-api-001",
    "tool_id": "ai_workflow_mapper",
    "input": {"documents": []},
    "options": {},
}


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _schema_store() -> dict:
    store: dict = {}
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        store[data["$id"]] = data
    return store


def _validate_output(instance: dict) -> None:
    schema = _load_schema("output.schema.json")
    store = _schema_store()
    resolver = jsonschema.RefResolver(base_uri=schema["$id"], referrer=schema, store=store)
    jsonschema.validate(instance, schema, resolver=resolver)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "service" in data


# ---------------------------------------------------------------------------
# POST /jobs — success paths
# ---------------------------------------------------------------------------


def test_submit_job_valid(client):
    resp = client.post("/jobs", json=_VALID_BODY)
    assert resp.status_code == 202
    data = resp.json()
    assert data["job_id"]
    assert data["tool_id"] == "ai_workflow_mapper"
    assert data["status"] in ("accepted", "running", "succeeded", "failed", "needs_review")
    assert "metadata" in data


def test_submit_job_with_optional_metadata(client):
    body = {**_VALID_BODY, "metadata": {"caller": "test"}}
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 202


# ---------------------------------------------------------------------------
# POST /jobs — validation failures → 400
# ---------------------------------------------------------------------------


def test_submit_job_wrong_tool_id(client):
    body = {**_VALID_BODY, "tool_id": "wrong_tool"}
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 400
    data = resp.json()
    assert data["error_code"] == "invalid_request"
    assert data["retryable"] is False


def test_submit_job_missing_request_id(client):
    body = {k: v for k, v in _VALID_BODY.items() if k != "request_id"}
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_request"


def test_submit_job_missing_input(client):
    body = {k: v for k, v in _VALID_BODY.items() if k != "input"}
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_request"


def test_submit_job_extra_field(client):
    body = {**_VALID_BODY, "unexpected_field": "should_fail"}
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_request"


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------


def test_get_job_exists(client):
    post_resp = client.post("/jobs", json=_VALID_BODY)
    assert post_resp.status_code == 202
    job_id = post_resp.json()["job_id"]

    get_resp = client.get(f"/jobs/{job_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["job_id"] == job_id
    assert data["tool_id"] == "ai_workflow_mapper"


def test_get_job_not_found(client):
    resp = client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_code"] == "job_not_found"
    assert data["retryable"] is False


# ---------------------------------------------------------------------------
# Schema conformance
# ---------------------------------------------------------------------------


def test_output_validates_against_schema(client):
    resp = client.post("/jobs", json=_VALID_BODY)
    assert resp.status_code == 202
    _validate_output(resp.json())


def test_error_validates_against_schema(client):
    schema = _load_schema("errors.schema.json")
    resp = client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    jsonschema.validate(resp.json(), schema)
