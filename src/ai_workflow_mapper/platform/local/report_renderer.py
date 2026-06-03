import time
from pathlib import Path
from typing import Any

import jinja2

from ai_workflow_mapper.platform.contracts.report_renderer import (
    ReportRendererConfig,
    ReportRendererError,
    ReportRendererErrorCode,
    ReportRendererOperation,
    ReportRendererRequest,
    ReportRendererResponse,
    ReportRendererStatus,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_SUPPORTED_FORMATS = {"markdown"}
_TEMPLATE_VERSION = "0.1.0"


class ReportRendererModuleError(Exception):
    def __init__(self, error: ReportRendererError) -> None:
        self.error = error
        super().__init__(error.message)


class LocalReportRenderer:
    """Project-local implementation of the report_renderer contract."""

    MODULE_ID = "report_renderer"

    def __init__(self, config: ReportRendererConfig) -> None:
        self._config = config
        templates_dir = Path(config.settings.get("templates_dir", str(_TEMPLATES_DIR)))
        self._output_dir = Path(config.settings.get("output_dir", "artifacts"))
        self._allowed_formats: set[str] = set(
            config.settings.get("allowed_formats", list(_SUPPORTED_FORMATS))
        )
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(templates_dir)),
            autoescape=False,
            undefined=jinja2.StrictUndefined,
        )

    def handle(self, request: ReportRendererRequest) -> ReportRendererResponse:
        t0 = time.monotonic()
        try:
            result, warnings = self._dispatch(request)
            return ReportRendererResponse(
                module_id=self.MODULE_ID,
                operation=request.operation,
                status=ReportRendererStatus.succeeded,
                result=result,
                warnings=warnings,
                metadata=self._make_metadata(t0),
                trace_id=request.trace_id,
            )
        except ReportRendererModuleError as exc:
            return ReportRendererResponse(
                module_id=self.MODULE_ID,
                operation=request.operation,
                status=ReportRendererStatus.failed,
                result={"error": exc.error.model_dump(exclude_none=True)},
                warnings=[],
                metadata=self._make_metadata(t0),
                trace_id=request.trace_id,
            )

    def get_config(self) -> ReportRendererConfig:
        return self._config

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self, request: ReportRendererRequest
    ) -> tuple[dict[str, Any], list[str]]:
        op = request.operation
        if op == ReportRendererOperation.render_report:
            return self._render_report(request.input, request.trace_id)
        if op == ReportRendererOperation.export_artifact:
            return self._export_artifact(request.input, request.trace_id)
        if op == ReportRendererOperation.validate_template:
            return self._validate_template(request.input, request.trace_id)
        raise ValueError(f"Unknown operation: {op}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _render_report(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        fmt: str = inp.get("format", "markdown")
        if fmt not in self._allowed_formats:
            raise ReportRendererModuleError(
                ReportRendererError(
                    operation=ReportRendererOperation.render_report,
                    error_code=ReportRendererErrorCode.format_unsupported,
                    message=f"Format '{fmt}' is not supported. Allowed: {self._allowed_formats}",
                    retryable=False,
                    trace_id=trace_id,
                )
            )

        template_id: str = inp.get("template_id", "report")
        template_file = f"{template_id}.md.j2"
        try:
            template = self._env.get_template(template_file)
        except jinja2.TemplateNotFound:
            raise ReportRendererModuleError(
                ReportRendererError(
                    operation=ReportRendererOperation.render_report,
                    error_code=ReportRendererErrorCode.template_not_found,
                    message=f"Template '{template_file}' not found",
                    retryable=False,
                    trace_id=trace_id,
                )
            )

        data: dict[str, Any] = inp.get("data", {})
        metadata: dict[str, Any] = inp.get("metadata", {})
        try:
            content = template.render(
                data=data,
                metadata=metadata,
                template_id=template_id,
                template_version=_TEMPLATE_VERSION,
            )
        except jinja2.UndefinedError as exc:
            raise ReportRendererModuleError(
                ReportRendererError(
                    operation=ReportRendererOperation.render_report,
                    error_code=ReportRendererErrorCode.render_failed,
                    message=f"Template rendering failed: {exc}",
                    retryable=False,
                    trace_id=trace_id,
                )
            ) from exc
        except jinja2.TemplateError as exc:
            raise ReportRendererModuleError(
                ReportRendererError(
                    operation=ReportRendererOperation.render_report,
                    error_code=ReportRendererErrorCode.render_failed,
                    message=f"Template rendering failed: {exc}",
                    retryable=False,
                    trace_id=trace_id,
                )
            ) from exc

        return {
            "content": content,
            "format": fmt,
            "template_id": template_id,
            "template_version": _TEMPLATE_VERSION,
            "char_count": len(content),
        }, []

    def _export_artifact(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        content: str = inp.get("content", "")
        filename: str = inp.get("filename", "report.md")
        fmt: str = inp.get("format", "markdown")

        if fmt not in self._allowed_formats:
            raise ReportRendererModuleError(
                ReportRendererError(
                    operation=ReportRendererOperation.export_artifact,
                    error_code=ReportRendererErrorCode.format_unsupported,
                    message=f"Format '{fmt}' is not supported",
                    retryable=False,
                    trace_id=trace_id,
                )
            )

        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = self._output_dir / filename
            artifact_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ReportRendererModuleError(
                ReportRendererError(
                    operation=ReportRendererOperation.export_artifact,
                    error_code=ReportRendererErrorCode.artifact_write_failed,
                    message=f"Failed to write artifact: {exc}",
                    retryable=True,
                    trace_id=trace_id,
                )
            ) from exc

        return {
            "artifact_path": str(artifact_path),
            "size_bytes": artifact_path.stat().st_size,
            "format": fmt,
        }, []

    def _validate_template(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        template_id: str = inp.get("template_id", "report")
        template_file = f"{template_id}.md.j2"
        errors: list[str] = []
        valid = True
        try:
            self._env.get_template(template_file)
        except jinja2.TemplateNotFound:
            valid = False
            errors.append(f"Template file '{template_file}' not found")
        except jinja2.TemplateSyntaxError as exc:
            valid = False
            errors.append(f"Syntax error in '{template_file}': {exc}")

        return {"template_id": template_id, "valid": valid, "errors": errors}, []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_metadata(self, t0: float) -> dict[str, Any]:
        return {
            "implementation": "local",
            "contract_version": "0.1.0",
            "latency_ms": round((time.monotonic() - t0) * 1000, 2),
        }
