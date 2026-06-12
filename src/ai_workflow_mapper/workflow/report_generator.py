"""Generate analysis report artifacts via LocalReportRenderer."""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_workflow_mapper.platform.contracts.report_renderer import (
    ReportRendererConfig,
    ReportRendererContext,
    ReportRendererOperation,
    ReportRendererRequest,
    ReportRendererStatus,
)
from ai_workflow_mapper.platform.local.report_renderer import LocalReportRenderer
from ai_workflow_mapper.workflow.domain import DiagramArtifact, OutputFormat

_log = logging.getLogger(__name__)

_FORMAT_EXTENSIONS: dict[str, str] = {
    "markdown": "report.md",
    "docx": "report.docx",
    "pdf": "report.pdf",
}

_MIME_TYPES: dict[str, str] = {
    "markdown": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}

_SYSTEM_CTX = ReportRendererContext(
    actor_id="system",
    tenant_id="system",
    environment="local",
)


class ReportGenerator:
    """Render and export workflow analysis reports."""

    def __init__(self, renderer: LocalReportRenderer | None = None) -> None:
        self._renderer = renderer

    def generate(
        self,
        template_data: dict[str, Any],
        metadata: dict[str, Any],
        output_format: OutputFormat,
        job_id: str,
    ) -> tuple[DiagramArtifact | None, list[str]]:
        """Return (report artifact or None on failure/skip, warnings). Never raises."""
        if output_format not in ("markdown", "docx", "pdf"):
            return None, []

        warnings: list[str] = []
        render_metadata = {
            **metadata,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "job_id": job_id,
        }

        job_output_dir = Path("artifacts") / job_id
        renderer = self._renderer or LocalReportRenderer(
            ReportRendererConfig(
                environment="local",
                implementation="local",
                settings={"output_dir": str(job_output_dir)},
                security={},
            )
        )

        render_resp = renderer.handle(
            ReportRendererRequest(
                request_id=str(uuid.uuid4()),
                operation=ReportRendererOperation.render_report,
                input={
                    "data": template_data,
                    "metadata": render_metadata,
                    "template_id": "report",
                    "format": output_format,
                },
                context=_SYSTEM_CTX,
                trace_id=job_id,
            )
        )
        warnings.extend(render_resp.warnings)

        if render_resp.status != ReportRendererStatus.succeeded:
            err = render_resp.result.get("error", {})
            msg = err.get("message", str(render_resp.result))
            warnings.append(f"Report render failed ({output_format}): {msg}")
            return None, warnings

        filename = _FORMAT_EXTENSIONS[output_format]
        export_input: dict[str, Any] = {
            "filename": filename,
            "format": output_format,
        }
        inline_content: str | None = None
        if output_format == "markdown":
            export_input["content"] = render_resp.result["content"]
            inline_content = render_resp.result["content"]
        else:
            export_input["content_b64"] = render_resp.result["content_b64"]

        export_resp = renderer.handle(
            ReportRendererRequest(
                request_id=str(uuid.uuid4()),
                operation=ReportRendererOperation.export_artifact,
                input=export_input,
                context=_SYSTEM_CTX,
                trace_id=job_id,
            )
        )
        if export_resp.status != ReportRendererStatus.succeeded:
            err = export_resp.result.get("error", {})
            warnings.append(
                f"Report export failed ({output_format}): "
                f"{err.get('message', export_resp.result)}"
            )
            return None, warnings

        rel_path = str(Path("artifacts") / job_id / filename).replace("\\", "/")
        if output_format == "markdown" and inline_content is not None:
            digest = hashlib.sha256(inline_content.encode("utf-8")).hexdigest()
        else:
            raw = render_resp.result.get("content_b64", "")
            digest = hashlib.sha256(base64.b64decode(raw)).hexdigest()

        artifact = DiagramArtifact(
            path=rel_path,
            type="report",
            description=f"Workflow analysis report ({output_format})",
            format=output_format,
            mime_type=_MIME_TYPES.get(output_format),
            content=inline_content,
            checksum=f"sha256:{digest}",
        )
        _log.info("Generated %s report at %s", output_format, rel_path)
        return artifact, warnings
