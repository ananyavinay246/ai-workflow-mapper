"""Contract tests for LocalEvaluationHarness (evaluation_harness module)."""

import json
from pathlib import Path

import jsonschema

from ai_workflow_mapper.platform.contracts.evaluation_harness import (
    EvaluationHarnessConfig,
    EvaluationHarnessContext,
    EvaluationHarnessOperation,
    EvaluationHarnessRequest,
)
from ai_workflow_mapper.platform.local.evaluation_harness import LocalEvaluationHarness

SCHEMAS_DIR = (
    Path(__file__).parents[2] / "shared_modules" / "evaluation_harness" / "schemas"
)


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _make_harness(tmp_path: Path, extra_settings: dict | None = None) -> LocalEvaluationHarness:
    settings: dict = {
        "pass_threshold_avg": 4.0,
        "pass_threshold_min": 3.0,
        "output_path": str(tmp_path / "eval_report.md"),
    }
    if extra_settings:
        settings.update(extra_settings)
    config = EvaluationHarnessConfig(
        environment="local",
        implementation="local",
        settings=settings,
        security={},
    )
    return LocalEvaluationHarness(config)


def _make_request(operation: EvaluationHarnessOperation, inp: dict) -> EvaluationHarnessRequest:
    return EvaluationHarnessRequest(
        request_id="test-eh-001",
        operation=operation,
        input=inp,
        context=EvaluationHarnessContext(actor_id="test", tenant_id="test", environment="local"),
        trace_id="trace-eh-001",
    )


def _write_fixture(fixtures_dir: Path, case_id: str, extra: dict | None = None) -> None:
    data = {
        "case_id": case_id,
        "request": {
            "request_id": f"req-{case_id}",
            "module_id": "document_loader",
            "operation": "detect_file_type",
            "input": {"filename": "test.txt"},
            "context": {"actor_id": "test", "tenant_id": "test", "environment": "local"},
            "trace_id": f"trace-{case_id}",
        },
        "expected_status": "succeeded",
        "rubric_scores": {
            "contract_validity": 4.5,
            "task_success": 4.0,
            "evidence_quality": 4.0,
            "safety": 5.0,
            "reliability": 4.0,
            "operator_clarity": 4.0,
        },
    }
    if extra:
        data.update(extra)
    (fixtures_dir / f"{case_id}.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# load_cases
# ---------------------------------------------------------------------------


def test_load_cases_happy_path(tmp_path):
    fixtures_dir = tmp_path / "golden"
    fixtures_dir.mkdir()
    _write_fixture(fixtures_dir, "case_001")
    _write_fixture(fixtures_dir, "case_002")

    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(EvaluationHarnessOperation.load_cases, {"fixtures_dir": str(fixtures_dir)})
    )
    assert resp.status.value == "succeeded"
    assert resp.result["count"] == 2
    assert len(resp.result["cases"]) == 2


def test_load_cases_empty_dir(tmp_path):
    fixtures_dir = tmp_path / "golden"
    fixtures_dir.mkdir()

    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(EvaluationHarnessOperation.load_cases, {"fixtures_dir": str(fixtures_dir)})
    )
    assert resp.status.value == "succeeded"
    assert resp.result["count"] == 0


def test_load_cases_missing_dir(tmp_path):
    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(
            EvaluationHarnessOperation.load_cases,
            {"fixtures_dir": str(tmp_path / "nonexistent")},
        )
    )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "eval_fixture_invalid"


def test_load_cases_invalid_fixture(tmp_path):
    fixtures_dir = tmp_path / "golden"
    fixtures_dir.mkdir()
    (fixtures_dir / "bad.json").write_text("{not json}", encoding="utf-8")

    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(EvaluationHarnessOperation.load_cases, {"fixtures_dir": str(fixtures_dir)})
    )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "eval_fixture_invalid"


def test_load_cases_missing_required_fields(tmp_path):
    fixtures_dir = tmp_path / "golden"
    fixtures_dir.mkdir()
    (fixtures_dir / "incomplete.json").write_text(
        json.dumps({"case_id": "x"}), encoding="utf-8"
    )

    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(EvaluationHarnessOperation.load_cases, {"fixtures_dir": str(fixtures_dir)})
    )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "eval_fixture_invalid"


# ---------------------------------------------------------------------------
# run_eval
# ---------------------------------------------------------------------------


def test_run_eval_happy_path(tmp_path):
    from ai_workflow_mapper.platform.contracts.document_loader import DocumentLoaderConfig
    from ai_workflow_mapper.platform.local.document_loader import LocalDocumentLoader

    loader = LocalDocumentLoader(
        DocumentLoaderConfig(
            environment="local",
            implementation="local",
            settings={},
            security={},
        )
    )

    cases = [
        {
            "case_id": "case_001",
            "request": {
                "request_id": "req-001",
                "module_id": "document_loader",
                "operation": "detect_file_type",
                "input": {"filename": "test.txt"},
                "context": {"actor_id": "test", "tenant_id": "test", "environment": "local"},
                "trace_id": "trace-001",
            },
            "expected_status": "succeeded",
            "rubric_scores": {},
        }
    ]

    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(
            EvaluationHarnessOperation.run_eval,
            {"cases": cases, "module_registry": {"document_loader": loader}},
        )
    )
    assert resp.status.value == "succeeded"
    assert resp.result["case_failures"] == 0
    assert resp.result["runner_errors"] == 0
    assert resp.result["case_results"][0]["status"] == "pass"


def test_run_eval_runner_failure(tmp_path):
    class BrokenModule:
        def handle(self, req):
            raise RuntimeError("Simulated failure")

    cases = [
        {
            "case_id": "case_001",
            "request": {
                "request_id": "req-001",
                "module_id": "document_loader",
                "operation": "detect_file_type",
                "input": {"filename": "test.txt"},
                "context": {"actor_id": "test", "tenant_id": "test", "environment": "local"},
                "trace_id": "trace-001",
            },
            "expected_status": "succeeded",
            "rubric_scores": {},
        }
    ]

    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(
            EvaluationHarnessOperation.run_eval,
            {"cases": cases, "module_registry": {"document_loader": BrokenModule()}},
        )
    )
    assert resp.status.value == "succeeded"
    assert resp.result["runner_errors"] == 1
    assert resp.result["case_results"][0]["status"] == "runner_error"


# ---------------------------------------------------------------------------
# score_results
# ---------------------------------------------------------------------------


def test_score_results_passes_threshold(tmp_path):
    harness = _make_harness(tmp_path)
    case_results = [
        {
            "case_id": "case_001",
            "status": "pass",
            "rubric_scores": {
                "contract_validity": 4.5,
                "task_success": 4.0,
                "evidence_quality": 4.0,
                "safety": 5.0,
                "reliability": 4.0,
                "operator_clarity": 4.0,
            },
        }
    ]
    resp = harness.handle(
        _make_request(EvaluationHarnessOperation.score_results, {"case_results": case_results})
    )
    assert resp.status.value == "succeeded"
    assert resp.result["passed"] is True
    assert resp.result["aggregate_avg"] >= 4.0


def test_score_results_fails_threshold(tmp_path):
    harness = _make_harness(tmp_path)
    case_results = [
        {
            "case_id": "case_001",
            "status": "fail",
            "rubric_scores": {
                "contract_validity": 2.0,
                "task_success": 2.0,
                "evidence_quality": 2.0,
                "safety": 2.0,
                "reliability": 2.0,
                "operator_clarity": 2.0,
            },
        }
    ]
    resp = harness.handle(
        _make_request(EvaluationHarnessOperation.score_results, {"case_results": case_results})
    )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "eval_threshold_failed"


def test_score_results_fails_dimension_min(tmp_path):
    harness = _make_harness(tmp_path)
    case_results = [
        {
            "case_id": "case_001",
            "status": "pass",
            "rubric_scores": {
                "contract_validity": 5.0,
                "task_success": 5.0,
                "evidence_quality": 5.0,
                "safety": 2.0,  # below threshold_min=3.0
                "reliability": 5.0,
                "operator_clarity": 5.0,
            },
        }
    ]
    resp = harness.handle(
        _make_request(EvaluationHarnessOperation.score_results, {"case_results": case_results})
    )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "eval_threshold_failed"


# ---------------------------------------------------------------------------
# emit_report
# ---------------------------------------------------------------------------


def test_emit_report_happy_path(tmp_path):
    harness = _make_harness(tmp_path)
    score_result = {
        "dimension_scores": {d: 4.5 for d in [
            "contract_validity", "task_success", "evidence_quality",
            "safety", "reliability", "operator_clarity",
        ]},
        "aggregate_avg": 4.5,
        "passed": True,
        "failed_dimensions": [],
    }
    resp = harness.handle(
        _make_request(
            EvaluationHarnessOperation.emit_report,
            {
                "score_result": score_result,
                "case_results": [{"case_id": "c1", "status": "pass", "rubric_scores": {}}],
                "output_path": str(tmp_path / "report.md"),
            },
        )
    )
    assert resp.status.value == "succeeded"
    report_path = Path(resp.result["report_path"])
    assert report_path.exists()
    assert resp.result["size_bytes"] > 0


def test_emit_report_write_failed(tmp_path):
    # Make output_path point into a file (not a dir) to trigger OSError
    blocker = tmp_path / "blocker"
    blocker.write_text("block")
    impossible_path = blocker / "report.md"

    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(
            EvaluationHarnessOperation.emit_report,
            {
                "score_result": {"aggregate_avg": 4.5, "passed": True, "dimension_scores": {}, "failed_dimensions": []},
                "case_results": [],
                "output_path": str(impossible_path),
            },
        )
    )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "eval_report_write_failed"


# ---------------------------------------------------------------------------
# Schema conformance
# ---------------------------------------------------------------------------


def test_input_validates_against_schema(tmp_path):
    schema = _load_schema("input.schema.json")
    fixtures_dir = tmp_path / "golden"
    fixtures_dir.mkdir()
    req = _make_request(EvaluationHarnessOperation.load_cases, {"fixtures_dir": str(fixtures_dir)})
    jsonschema.validate(req.model_dump(), schema)


def test_output_validates_against_schema(tmp_path):
    schema = _load_schema("output.schema.json")
    fixtures_dir = tmp_path / "golden"
    fixtures_dir.mkdir()
    _write_fixture(fixtures_dir, "case_001")

    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(EvaluationHarnessOperation.load_cases, {"fixtures_dir": str(fixtures_dir)})
    )
    jsonschema.validate(resp.model_dump(exclude_none=True), schema)


def test_error_validates_against_schema(tmp_path):
    schema = _load_schema("error.schema.json")
    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(
            EvaluationHarnessOperation.load_cases,
            {"fixtures_dir": str(tmp_path / "nonexistent")},
        )
    )
    assert resp.status.value == "failed"
    jsonschema.validate(resp.result["error"], schema)


def test_config_validates_against_schema(tmp_path):
    schema = _load_schema("config.schema.json")
    harness = _make_harness(tmp_path)
    jsonschema.validate(harness.get_config().model_dump(exclude_none=True), schema)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_backward_compatible_fields_stable(tmp_path):
    fixtures_dir = tmp_path / "golden"
    fixtures_dir.mkdir()

    harness = _make_harness(tmp_path)
    resp = harness.handle(
        _make_request(EvaluationHarnessOperation.load_cases, {"fixtures_dir": str(fixtures_dir)})
    )
    for field in ("module_id", "operation", "status", "result", "warnings", "metadata", "trace_id"):
        assert hasattr(resp, field)
    assert resp.module_id == "evaluation_harness"
    assert resp.trace_id == "trace-eh-001"
