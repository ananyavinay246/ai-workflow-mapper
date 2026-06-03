"""CLI entrypoint: python -m ai_workflow_mapper.eval.run_eval"""

import argparse
import sys
import uuid

from ai_workflow_mapper.platform.contracts.evaluation_harness import (
    EvaluationHarnessConfig,
    EvaluationHarnessContext,
    EvaluationHarnessOperation,
    EvaluationHarnessRequest,
)
from ai_workflow_mapper.platform.contracts.document_loader import DocumentLoaderConfig
from ai_workflow_mapper.platform.local.document_loader import LocalDocumentLoader
from ai_workflow_mapper.platform.local.evaluation_harness import LocalEvaluationHarness


def _build_module_registry() -> dict:
    doc_loader = LocalDocumentLoader(
        DocumentLoaderConfig(
            environment="local",
            implementation="local",
            settings={},
            security={},
        )
    )
    return {"document_loader": doc_loader}


def _make_harness(args: argparse.Namespace) -> LocalEvaluationHarness:
    config = EvaluationHarnessConfig(
        environment="local",
        implementation="local",
        settings={
            "pass_threshold_avg": args.threshold_avg,
            "pass_threshold_min": args.threshold_min,
            "output_path": args.output,
        },
        security={},
    )
    return LocalEvaluationHarness(config)


def _make_context() -> EvaluationHarnessContext:
    return EvaluationHarnessContext(actor_id="eval-cli", tenant_id="local", environment="local")


def _req(harness_op: EvaluationHarnessOperation, inp: dict, trace_id: str) -> EvaluationHarnessRequest:
    return EvaluationHarnessRequest(
        request_id=str(uuid.uuid4()),
        operation=harness_op,
        input=inp,
        context=_make_context(),
        trace_id=trace_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run evaluation for AI Workflow Mapper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--fixtures", default="fixtures/golden", help="Path to golden fixtures dir")
    parser.add_argument("--rubric", default="eval/rubric.md", help="Path to rubric file")
    parser.add_argument("--output", default="eval_report.md", help="Path to write eval report")
    parser.add_argument("--threshold-avg", type=float, default=4.0, help="Min passing average score")
    parser.add_argument("--threshold-min", type=float, default=3.0, help="Min score per dimension")
    parser.add_argument("--trace-id", default=None, help="Trace ID for this run (auto-generated if omitted)")
    args = parser.parse_args()

    trace_id = args.trace_id or str(uuid.uuid4())
    harness = _make_harness(args)
    module_registry = _build_module_registry()

    # Step 1: load cases
    load_resp = harness.handle(_req(EvaluationHarnessOperation.load_cases, {"fixtures_dir": args.fixtures}, trace_id))
    if load_resp.status.value == "failed":
        print(f"[FAIL] load_cases: {load_resp.result['error']['message']}")
        sys.exit(1)
    cases = load_resp.result["cases"]
    print(f"Loaded {load_resp.result['count']} fixture(s) from '{args.fixtures}'")

    # Step 2: run eval
    run_resp = harness.handle(
        _req(
            EvaluationHarnessOperation.run_eval,
            {"cases": cases, "module_registry": module_registry},
            trace_id,
        )
    )
    if run_resp.status.value == "failed":
        print(f"[FAIL] run_eval: {run_resp.result['error']['message']}")
        sys.exit(1)
    case_results = run_resp.result["case_results"]
    print(
        f"Ran {len(case_results)} case(s): "
        f"{run_resp.result['case_failures']} failure(s), "
        f"{run_resp.result.get('runner_errors', 0)} runner error(s)"
    )

    # Step 3: score results
    score_resp = harness.handle(
        _req(EvaluationHarnessOperation.score_results, {"case_results": case_results}, trace_id)
    )
    passed: bool
    score_result: dict
    if score_resp.status.value == "failed":
        error = score_resp.result["error"]
        print(f"[FAIL] score_results: {error['message']}")
        passed = False
        score_result = {}
    else:
        passed = score_resp.result["passed"]
        score_result = score_resp.result
        print(f"Aggregate score: {score_result['aggregate_avg']:.2f} (threshold: {args.threshold_avg})")
        print("\nDimension scores:")
        for dim, score in score_result.get("dimension_scores", {}).items():
            marker = "  " if score >= args.threshold_min else "! "
            print(f"  {marker}{dim}: {score:.2f}")

    # Step 4: emit report
    emit_resp = harness.handle(
        _req(
            EvaluationHarnessOperation.emit_report,
            {
                "score_result": score_result,
                "case_results": case_results,
                "output_path": args.output,
                "fixtures_dir": args.fixtures,
                "rubric_path": args.rubric,
                "runner_errors": run_resp.result.get("runner_errors", 0),
            },
            trace_id,
        )
    )
    if emit_resp.status.value == "failed":
        print(f"[WARN] emit_report failed: {emit_resp.result['error']['message']}")
    else:
        print(f"\nReport written to: {emit_resp.result['report_path']}")

    # Final verdict
    verdict = "PASS" if passed else "FAIL"
    print(f"\nVerdict: {verdict}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
