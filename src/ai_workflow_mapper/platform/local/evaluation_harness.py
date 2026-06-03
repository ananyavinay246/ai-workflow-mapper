import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jinja2

from ai_workflow_mapper.platform.contracts.evaluation_harness import (
    EvaluationHarnessConfig,
    EvaluationHarnessError,
    EvaluationHarnessErrorCode,
    EvaluationHarnessOperation,
    EvaluationHarnessRequest,
    EvaluationHarnessResponse,
    EvaluationHarnessStatus,
)

_RUBRIC_DIMENSIONS = [
    "contract_validity",
    "task_success",
    "evidence_quality",
    "safety",
    "reliability",
    "operator_clarity",
]

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_EVAL_TEMPLATE = "eval_report.md.j2"


class EvaluationHarnessModuleError(Exception):
    def __init__(self, error: EvaluationHarnessError) -> None:
        self.error = error
        super().__init__(error.message)


class LocalEvaluationHarness:
    """Project-local implementation of the evaluation_harness contract."""

    MODULE_ID = "evaluation_harness"
    DEFAULT_THRESHOLD_AVG = 4.0
    DEFAULT_THRESHOLD_MIN = 3.0

    def __init__(self, config: EvaluationHarnessConfig) -> None:
        self._config = config
        s = config.settings
        self._threshold_avg: float = float(s.get("pass_threshold_avg", self.DEFAULT_THRESHOLD_AVG))
        self._threshold_min: float = float(s.get("pass_threshold_min", self.DEFAULT_THRESHOLD_MIN))
        self._output_path = Path(s.get("output_path", "eval_report.md"))
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=False,
            undefined=jinja2.Undefined,
        )

    def handle(self, request: EvaluationHarnessRequest) -> EvaluationHarnessResponse:
        t0 = time.monotonic()
        try:
            result, warnings = self._dispatch(request)
            return EvaluationHarnessResponse(
                module_id=self.MODULE_ID,
                operation=request.operation,
                status=EvaluationHarnessStatus.succeeded,
                result=result,
                warnings=warnings,
                metadata=self._make_metadata(t0),
                trace_id=request.trace_id,
            )
        except EvaluationHarnessModuleError as exc:
            return EvaluationHarnessResponse(
                module_id=self.MODULE_ID,
                operation=request.operation,
                status=EvaluationHarnessStatus.failed,
                result={"error": exc.error.model_dump(exclude_none=True)},
                warnings=[],
                metadata=self._make_metadata(t0),
                trace_id=request.trace_id,
            )

    def get_config(self) -> EvaluationHarnessConfig:
        return self._config

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self, request: EvaluationHarnessRequest
    ) -> tuple[dict[str, Any], list[str]]:
        op = request.operation
        if op == EvaluationHarnessOperation.load_cases:
            return self._load_cases(request.input, request.trace_id)
        if op == EvaluationHarnessOperation.run_eval:
            return self._run_eval(request.input, request.trace_id)
        if op == EvaluationHarnessOperation.score_results:
            return self._score_results(request.input, request.trace_id)
        if op == EvaluationHarnessOperation.emit_report:
            return self._emit_report(request.input, request.trace_id)
        raise ValueError(f"Unknown operation: {op}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _load_cases(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        fixtures_dir = Path(inp.get("fixtures_dir", "fixtures/golden"))
        if not fixtures_dir.exists():
            raise EvaluationHarnessModuleError(
                EvaluationHarnessError(
                    operation=EvaluationHarnessOperation.load_cases,
                    error_code=EvaluationHarnessErrorCode.eval_fixture_invalid,
                    message=f"Fixtures directory not found: {fixtures_dir}",
                    retryable=False,
                    trace_id=trace_id,
                )
            )

        fixture_files = sorted(fixtures_dir.glob("*.json"))
        cases: list[dict[str, Any]] = []
        for path in fixture_files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise EvaluationHarnessModuleError(
                    EvaluationHarnessError(
                        operation=EvaluationHarnessOperation.load_cases,
                        error_code=EvaluationHarnessErrorCode.eval_fixture_invalid,
                        message=f"Failed to parse fixture '{path.name}': {exc}",
                        retryable=False,
                        trace_id=trace_id,
                    )
                ) from exc

            # Require at minimum case_id and request
            if "case_id" not in data or "request" not in data:
                raise EvaluationHarnessModuleError(
                    EvaluationHarnessError(
                        operation=EvaluationHarnessOperation.load_cases,
                        error_code=EvaluationHarnessErrorCode.eval_fixture_invalid,
                        message=f"Fixture '{path.name}' missing required fields: case_id, request",
                        retryable=False,
                        trace_id=trace_id,
                    )
                )
            cases.append(data)

        return {"cases": cases, "count": len(cases)}, []

    def _run_eval(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        cases: list[dict[str, Any]] = inp.get("cases", [])
        module_registry: dict[str, Any] = inp.get("module_registry", {})

        case_results: list[dict[str, Any]] = []
        runner_errors = 0
        case_failures = 0

        for case in cases:
            case_id = case.get("case_id", "unknown")
            request_data = case.get("request", {})
            module_id = request_data.get("module_id", "")
            expected_status = case.get("expected_status", "succeeded")

            try:
                module = module_registry.get(module_id)
                if module is None:
                    raise RuntimeError(f"No module registered for module_id='{module_id}'")

                # Reconstruct a typed request and call the module
                from ai_workflow_mapper.platform.contracts.document_loader import (  # noqa: PLC0415
                    DocumentLoaderContext,
                    DocumentLoaderOperation,
                    DocumentLoaderRequest,
                )

                if module_id == "document_loader":
                    req = DocumentLoaderRequest(
                        request_id=request_data.get("request_id", str(uuid.uuid4())),
                        operation=DocumentLoaderOperation(request_data["operation"]),
                        input=request_data.get("input", {}),
                        context=DocumentLoaderContext(**request_data.get("context", {
                            "actor_id": "eval", "tenant_id": "eval", "environment": "local"
                        })),
                        trace_id=request_data.get("trace_id", trace_id),
                    )
                    response = module.handle(req)
                    actual_status = response.status.value
                else:
                    actual_status = "unknown"
                    response = None

                status = "pass" if actual_status == expected_status else "fail"
                if status == "fail":
                    case_failures += 1

                case_results.append({
                    "case_id": case_id,
                    "module_id": module_id,
                    "status": status,
                    "expected_status": expected_status,
                    "actual_status": actual_status,
                    "rubric_scores": case.get("rubric_scores", {}),
                })

            except Exception as exc:
                runner_errors += 1
                case_results.append({
                    "case_id": case_id,
                    "module_id": module_id,
                    "status": "runner_error",
                    "error": str(exc),
                    "rubric_scores": {},
                })

        return {
            "case_results": case_results,
            "runner_errors": runner_errors,
            "case_failures": case_failures,
        }, []

    def _score_results(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        case_results: list[dict[str, Any]] = inp.get("case_results", [])

        # Collect per-dimension scores across all cases
        dimension_totals: dict[str, list[float]] = {dim: [] for dim in _RUBRIC_DIMENSIONS}
        for case in case_results:
            scores: dict[str, Any] = case.get("rubric_scores", {})
            for dim in _RUBRIC_DIMENSIONS:
                if dim in scores:
                    try:
                        dimension_totals[dim].append(float(scores[dim]))
                    except (TypeError, ValueError):
                        pass

        dimension_scores: dict[str, float] = {}
        for dim, values in dimension_totals.items():
            dimension_scores[dim] = round(sum(values) / len(values), 2) if values else 0.0

        scored_dims = [v for v in dimension_scores.values() if v > 0]
        aggregate_avg = round(sum(scored_dims) / len(scored_dims), 2) if scored_dims else 0.0

        failed_dimensions = [
            dim for dim, score in dimension_scores.items()
            if 0 < score < self._threshold_min
        ]
        passed = aggregate_avg >= self._threshold_avg and not failed_dimensions

        if not passed:
            raise EvaluationHarnessModuleError(
                EvaluationHarnessError(
                    operation=EvaluationHarnessOperation.score_results,
                    error_code=EvaluationHarnessErrorCode.eval_threshold_failed,
                    message=(
                        f"Evaluation failed: avg={aggregate_avg:.2f} "
                        f"(threshold={self._threshold_avg}), "
                        f"failed_dimensions={failed_dimensions}"
                    ),
                    retryable=False,
                    trace_id=trace_id,
                )
            )

        return {
            "dimension_scores": dimension_scores,
            "aggregate_avg": aggregate_avg,
            "passed": passed,
            "failed_dimensions": failed_dimensions,
        }, []

    def _emit_report(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        score_result: dict[str, Any] = inp.get("score_result", {})
        case_results: list[dict[str, Any]] = inp.get("case_results", [])
        output_path = Path(inp.get("output_path", str(self._output_path)))

        try:
            template = self._env.get_template(_EVAL_TEMPLATE)
        except jinja2.TemplateNotFound:
            raise EvaluationHarnessModuleError(
                EvaluationHarnessError(
                    operation=EvaluationHarnessOperation.emit_report,
                    error_code=EvaluationHarnessErrorCode.eval_report_write_failed,
                    message=f"Eval report template '{_EVAL_TEMPLATE}' not found",
                    retryable=False,
                    trace_id=trace_id,
                )
            )

        cases_loaded = len(case_results)
        cases_passed = sum(1 for c in case_results if c.get("status") == "pass")
        cases_failed = sum(1 for c in case_results if c.get("status") in ("fail", "runner_error"))

        content = template.render(
            run_id=trace_id,
            fixtures_dir=inp.get("fixtures_dir", "fixtures/golden"),
            rubric_path=inp.get("rubric_path", "eval/rubric.md"),
            generated_at=datetime.now(timezone.utc).isoformat(),
            cases_loaded=cases_loaded,
            cases_passed=cases_passed,
            cases_failed=cases_failed,
            runner_errors=inp.get("runner_errors", 0),
            aggregate_avg=score_result.get("aggregate_avg", 0.0),
            passed=score_result.get("passed", False),
            dimension_scores=score_result.get("dimension_scores", {}),
            threshold_avg=self._threshold_avg,
            threshold_min=self._threshold_min,
            case_results=case_results,
            failed_dimensions=score_result.get("failed_dimensions", []),
        )

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise EvaluationHarnessModuleError(
                EvaluationHarnessError(
                    operation=EvaluationHarnessOperation.emit_report,
                    error_code=EvaluationHarnessErrorCode.eval_report_write_failed,
                    message=f"Failed to write eval report: {exc}",
                    retryable=True,
                    trace_id=trace_id,
                )
            ) from exc

        return {"report_path": str(output_path), "size_bytes": output_path.stat().st_size}, []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_metadata(self, t0: float) -> dict[str, Any]:
        return {
            "implementation": "local",
            "contract_version": "0.1.0",
            "latency_ms": round((time.monotonic() - t0) * 1000, 2),
        }
