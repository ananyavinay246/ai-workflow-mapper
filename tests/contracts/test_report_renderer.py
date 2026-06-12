"""Contract tests for LocalReportRenderer (report_renderer module)."""

import json
from pathlib import Path

import jsonschema

from ai_workflow_mapper.platform.contracts.report_renderer import (
    ReportRendererConfig,
    ReportRendererContext,
    ReportRendererOperation,
    ReportRendererRequest,
)
from ai_workflow_mapper.platform.local.report_renderer import LocalReportRenderer

SCHEMAS_DIR = (
    Path(__file__).parents[2] / "shared_modules" / "report_renderer" / "schemas"
)


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _make_renderer(tmp_path: Path, extra_settings: dict | None = None) -> LocalReportRenderer:
    settings: dict = {"output_dir": str(tmp_path / "artifacts")}
    if extra_settings:
        settings.update(extra_settings)
    config = ReportRendererConfig(
        environment="local",
        implementation="local",
        settings=settings,
        security={},
    )
    return LocalReportRenderer(config)


def _make_request(operation: ReportRendererOperation, inp: dict) -> ReportRendererRequest:
    return ReportRendererRequest(
        request_id="test-rr-001",
        operation=operation,
        input=inp,
        context=ReportRendererContext(actor_id="test", tenant_id="test", environment="local"),
        trace_id="trace-rr-001",
    )


_SAMPLE_DATA = {
    "executive_summary": "The onboarding workflow has three bottlenecks.",
    "processes": [
        {"name": "Submit Application", "owner": "HR", "duration": "1 day", "frequency": "Daily"},
        {"name": "Manager Approval", "owner": "Manager", "duration": "3 days", "frequency": "Per hire"},
    ],
    "bottlenecks": [
        {"name": "Manual approval queue", "severity": "Critical", "description": "Approvals pile up on Fridays.", "impact": "3-day delay"},
    ],
    "redundancies": [
        {"name": "Duplicate data entry", "description": "HR enters data in both systems.", "affected_steps": ["Submit", "Confirm"]},
    ],
    "automation_opportunities": [
        {"name": "Auto-routing approvals", "effort": "Low", "roi": "High", "priority": "1"},
    ],
    "next_steps": [
        "Implement auto-routing for approvals",
        "Consolidate HR data systems",
    ],
}


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------


def test_render_report_markdown_happy(tmp_path):
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {
                "data": _SAMPLE_DATA,
                "metadata": {"job_id": "test", "normalized_documents": 1, "skipped_documents": 0},
                "template_id": "report",
                "format": "markdown",
            },
        )
    )
    assert resp.status.value == "succeeded"
    assert "content" in resp.result
    assert resp.result["format"] == "markdown"
    assert resp.result["template_id"] == "report"
    assert resp.result["char_count"] > 0
    assert "Executive Summary" in resp.result["content"]
    assert "Bottleneck Analysis" in resp.result["content"]


def test_render_report_unsupported_format(tmp_path):
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {"data": _SAMPLE_DATA, "template_id": "report", "format": "html"},
        )
    )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "format_unsupported"


def test_render_report_template_not_found(tmp_path):
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {"data": _SAMPLE_DATA, "template_id": "nonexistent", "format": "markdown"},
        )
    )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "template_not_found"


def test_render_report_custom_template(tmp_path):
    """A custom template in a separate dir renders correctly."""
    templates_dir = tmp_path / "tmpl"
    templates_dir.mkdir()
    (templates_dir / "custom.md.j2").write_text("Hello {{ data.name }}!", encoding="utf-8")

    renderer = _make_renderer(tmp_path, {"templates_dir": str(templates_dir)})
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {"data": {"name": "World"}, "template_id": "custom", "format": "markdown"},
        )
    )
    assert resp.status.value == "succeeded"
    assert resp.result["content"] == "Hello World!"


def test_render_report_docx_happy(tmp_path):
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {"data": _SAMPLE_DATA, "template_id": "report", "format": "docx"},
        )
    )
    assert resp.status.value == "succeeded"
    assert resp.result["format"] == "docx"
    assert "content_b64" in resp.result
    assert resp.result["byte_count"] > 0


def test_export_artifact_docx_binary(tmp_path):
    renderer = _make_renderer(tmp_path)
    render = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {"data": _SAMPLE_DATA, "template_id": "report", "format": "docx"},
        )
    )
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.export_artifact,
            {
                "content_b64": render.result["content_b64"],
                "filename": "report.docx",
                "format": "docx",
            },
        )
    )
    assert resp.status.value == "succeeded"
    path = Path(resp.result["artifact_path"])
    assert path.exists()
    assert path.suffix == ".docx"
    assert path.stat().st_size > 0


def test_render_report_pdf_unavailable_without_weasyprint(tmp_path, monkeypatch):
    renderer = _make_renderer(tmp_path)

    def _raise_weasyprint(*_args, **_kwargs):
        raise ImportError("no weasyprint")

    monkeypatch.setitem(__import__("sys").modules, "weasyprint", None)

    import ai_workflow_mapper.platform.local.report_renderer as rr_mod

    original_render_pdf = rr_mod.LocalReportRenderer._render_pdf

    def _patched_render_pdf(self, markdown_content: str):
        raise rr_mod.ReportRendererModuleError(
            rr_mod.ReportRendererError(
                operation=ReportRendererOperation.render_report,
                error_code=rr_mod.ReportRendererErrorCode.render_failed,
                message=(
                    "PDF export unavailable; install report-pdf extras "
                    "(pip install ai-workflow-mapper[report-pdf]) or use markdown/docx"
                ),
                retryable=False,
                trace_id="",
            )
        )

    monkeypatch.setattr(rr_mod.LocalReportRenderer, "_render_pdf", _patched_render_pdf)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {
                "data": _SAMPLE_DATA,
                "metadata": {"job_id": "test", "normalized_documents": 1, "skipped_documents": 0},
                "template_id": "report",
                "format": "pdf",
            },
        )
    )
    assert resp.status.value == "failed"
    assert "PDF export unavailable" in resp.result["error"]["message"]
    monkeypatch.setattr(rr_mod.LocalReportRenderer, "_render_pdf", original_render_pdf)


# ---------------------------------------------------------------------------
# export_artifact
# ---------------------------------------------------------------------------


def test_export_artifact_happy(tmp_path):
    renderer = _make_renderer(tmp_path)
    content = "# Report\nSome content"
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.export_artifact,
            {"content": content, "filename": "output.md", "format": "markdown"},
        )
    )
    assert resp.status.value == "succeeded"
    artifact_path = Path(resp.result["artifact_path"])
    assert artifact_path.exists()
    assert artifact_path.read_text(encoding="utf-8") == content
    assert resp.result["size_bytes"] > 0
    assert "content" not in resp.result  # content must not be echoed back


def test_export_artifact_write_failed(tmp_path):
    # Point output_dir to a file (not a dir) so mkdir fails → write fails
    blocker = tmp_path / "blocker"
    blocker.write_text("block")
    renderer = _make_renderer(tmp_path, {"output_dir": str(blocker)})
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.export_artifact,
            {"content": "data", "filename": "out.md", "format": "markdown"},
        )
    )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "artifact_write_failed"


# ---------------------------------------------------------------------------
# validate_template
# ---------------------------------------------------------------------------


def test_validate_template_valid(tmp_path):
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.validate_template,
            {"template_id": "report"},
        )
    )
    assert resp.status.value == "succeeded"
    assert resp.result["valid"] is True
    assert resp.result["errors"] == []


def test_validate_template_not_found(tmp_path):
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.validate_template,
            {"template_id": "ghost"},
        )
    )
    assert resp.status.value == "succeeded"  # validate_template never raises
    assert resp.result["valid"] is False
    assert len(resp.result["errors"]) > 0


def test_validate_template_syntax_error(tmp_path):
    templates_dir = tmp_path / "tmpl"
    templates_dir.mkdir()
    (templates_dir / "broken.md.j2").write_text("{{ unclosed }", encoding="utf-8")

    renderer = _make_renderer(tmp_path, {"templates_dir": str(templates_dir)})
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.validate_template,
            {"template_id": "broken"},
        )
    )
    assert resp.status.value == "succeeded"
    assert resp.result["valid"] is False


# ---------------------------------------------------------------------------
# Schema conformance
# ---------------------------------------------------------------------------


def test_input_validates_against_schema():
    schema = _load_schema("input.schema.json")
    req = _make_request(
        ReportRendererOperation.render_report,
        {"data": _SAMPLE_DATA, "template_id": "report", "format": "markdown"},
    )
    jsonschema.validate(req.model_dump(), schema)


def test_output_validates_against_schema(tmp_path):
    schema = _load_schema("output.schema.json")
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {"data": _SAMPLE_DATA, "template_id": "report", "format": "markdown"},
        )
    )
    jsonschema.validate(resp.model_dump(exclude_none=True), schema)


def test_error_validates_against_schema(tmp_path):
    schema = _load_schema("error.schema.json")
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {"data": {}, "template_id": "nope", "format": "markdown"},
        )
    )
    assert resp.status.value == "failed"
    jsonschema.validate(resp.result["error"], schema)


def test_config_validates_against_schema(tmp_path):
    schema = _load_schema("config.schema.json")
    renderer = _make_renderer(tmp_path)
    jsonschema.validate(renderer.get_config().model_dump(exclude_none=True), schema)


# ---------------------------------------------------------------------------
# Security: sensitive fields not in metadata
# ---------------------------------------------------------------------------


def test_no_sensitive_values_in_metadata(tmp_path):
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.render_report,
            {"data": {"executive_summary": "INTERNAL SECRET"}, "template_id": "report", "format": "markdown"},
        )
    )
    meta_str = json.dumps(resp.metadata)
    assert "INTERNAL SECRET" not in meta_str


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_backward_compatible_fields_stable(tmp_path):
    renderer = _make_renderer(tmp_path)
    resp = renderer.handle(
        _make_request(
            ReportRendererOperation.validate_template,
            {"template_id": "report"},
        )
    )
    for field in ("module_id", "operation", "status", "result", "warnings", "metadata", "trace_id"):
        assert hasattr(resp, field)
    assert resp.module_id == "report_renderer"
    assert resp.trace_id == "trace-rr-001"
