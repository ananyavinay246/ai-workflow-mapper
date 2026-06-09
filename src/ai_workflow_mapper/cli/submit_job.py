"""Build JobInput payloads from local files and run or submit jobs."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

from ai_workflow_mapper.api.models import JobInput
from ai_workflow_mapper.api.processor import JobProcessResult, process
from ai_workflow_mapper.workflow.domain import InputDocument, JobMode, JobOptions, SourceType, WorkflowInput

_SUPPORTED_EXTENSIONS = {".txt", ".md", ".json", ".pdf", ".docx"}


def _encode_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _guess_source_type(path: Path, override: SourceType | None) -> SourceType:
    if override is not None:
        return override
    name = path.name.lower()
    if "interview" in name or "transcript" in name:
        return "interview"
    if "sop" in name or "procedure" in name or "runbook" in name:
        return "sop"
    return "document"


def build_job_input(
    paths: list[Path],
    *,
    description: str | None = None,
    source_type: SourceType | None = None,
    request_id: str | None = None,
    max_cost_usd: float | None = None,
    mode: JobMode = "standard",
    mermaid: bool = False,
) -> JobInput:
    documents: list[InputDocument] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Not a file: {resolved}")
        ext = resolved.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(_SUPPORTED_EXTENSIONS))
            raise ValueError(
                f"Unsupported file type {ext!r} for {resolved.name}. Supported: {supported}"
            )
        documents.append(
            InputDocument(
                filename=resolved.name,
                content_b64=_encode_file(resolved),
                source_type=_guess_source_type(resolved, source_type),
            )
        )

    options = JobOptions(mode=mode)
    updates: dict[str, Any] = {}
    if max_cost_usd is not None:
        updates["max_cost_usd"] = max_cost_usd
    if mermaid:
        updates["diagram_formats"] = ["mermaid"]
    if updates:
        options = options.model_copy(update=updates)

    return JobInput(
        request_id=request_id or f"cli-{uuid.uuid4()}",
        input=WorkflowInput(documents=documents, description=description),
        options=options,
    )


def run_local(job_input: JobInput) -> JobProcessResult:
    return process(job_input)


def submit_http(job_input: JobInput, base_url: str, timeout_s: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/jobs"
    payload = job_input.model_dump(mode="json")
    response = httpx.post(url, json=payload, timeout=timeout_s)
    response.raise_for_status()
    return response.json()


def _print_summary(result: dict[str, Any]) -> None:
    status = result.get("status", "unknown")
    print(f"status: {status}", file=sys.stderr)
    job_result = result.get("result") or {}
    summary = job_result.get("normalization_summary") or {}
    if summary:
        print(
            f"normalized: {summary.get('normalized_documents', 0)}, "
            f"skipped: {summary.get('skipped_documents', 0)}",
            file=sys.stderr,
        )
    graph = job_result.get("process_graph")
    if graph:
        print(
            f"process_graph: {len(graph.get('nodes', []))} nodes, "
            f"{len(graph.get('edges', []))} edges, "
            f"{len(graph.get('actors', []))} actors",
            file=sys.stderr,
        )
    artifacts = result.get("artifacts") or []
    if artifacts:
        types = ", ".join(
            f"{a.get('diagram_type', 'diagram')} ({a.get('path', '')})" for a in artifacts
        )
        print(f"artifacts: {len(artifacts)} ({types})", file=sys.stderr)
    warnings = summary.get("warnings") or result.get("warnings") or []
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Submit local documents to AI Workflow Mapper (API or in-process)."
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="Paths to .txt, .md, .json, .pdf, or .docx files",
    )
    parser.add_argument(
        "--description",
        "-d",
        help="Optional free-text process description (interview notes, context)",
    )
    parser.add_argument(
        "--source-type",
        choices=["document", "interview", "sop", "diagram", "tool_export"],
        help="Apply this source_type to every uploaded file",
    )
    parser.add_argument(
        "--local",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the workflow in-process (default). Use --no-local to POST to the API.",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
        help="API base URL when using --no-local (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="HTTP timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        help="Per-job LLM cost ceiling override",
    )
    parser.add_argument(
        "--mode",
        choices=["standard", "fast", "thorough"],
        default="standard",
        help="Analysis mode passed in job options",
    )
    parser.add_argument(
        "--mermaid",
        action="store_true",
        help="Generate Mermaid flowchart and swimlane diagrams (sets diagram_formats)",
    )
    parser.add_argument(
        "--request-id",
        help="Caller request id (default: generated UUID)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write full JSON response to this file",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from ai_workflow_mapper.platform.env_loader import load_project_env

    load_project_env()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        job_input = build_job_input(
            args.files,
            description=args.description,
            source_type=args.source_type,
            request_id=args.request_id,
            max_cost_usd=args.max_cost_usd,
            mode=args.mode,
            mermaid=args.mermaid,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.local:
            out = run_local(job_input)
            payload = {
                "job_id": job_input.request_id,
                "tool_id": "ai_workflow_mapper",
                "status": "succeeded",
                "result": out.result,
                "artifacts": out.artifacts or None,
                "warnings": out.warnings or None,
                "metadata": {"source": "cli", "mode": "local"},
            }
        else:
            payload = submit_http(job_input, args.url, args.timeout)
    except httpx.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    text = json.dumps(payload, indent=indent)
    print(text)

    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)

    _print_summary(payload)
    status = payload.get("status")
    return 0 if status in ("succeeded", "accepted", "needs_review") else 1


if __name__ == "__main__":
    raise SystemExit(main())
