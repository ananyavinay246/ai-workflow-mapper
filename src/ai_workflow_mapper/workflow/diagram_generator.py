"""Diagram generator — converts ProcessGraph into export artifacts."""

from __future__ import annotations

import logging

from ai_workflow_mapper.platform.local.artifact_writer import ArtifactWriter
from ai_workflow_mapper.platform.local.kroki_client import KrokiClient, KrokiError
from ai_workflow_mapper.workflow.domain import (
    DiagramArtifact,
    DiagramType,
    JobOptions,
    ProcessGraph,
)
from ai_workflow_mapper.workflow.mermaid_renderer import (
    MermaidRenderError,
    render_flowchart,
    render_swimlane,
)

_log = logging.getLogger(__name__)

_SUPPORTED_MERMAID_TYPES: frozenset[DiagramType] = frozenset({"flowchart", "swimlane"})
_DEFAULT_MERMAID_TYPES: list[DiagramType] = ["flowchart", "swimlane"]

_RENDERERS = {
    "flowchart": render_flowchart,
    "swimlane": render_swimlane,
}

_MMD_FILENAMES = {
    "flowchart": "flowchart.mmd",
    "swimlane": "swimlane.mmd",
}

_PNG_FILENAMES = {
    "flowchart": "flowchart.png",
    "swimlane": "swimlane.png",
}


class MermaidDiagramGenerator:
    """Generate Mermaid diagram artifacts from a ProcessGraph."""

    def __init__(
        self,
        writer: ArtifactWriter | None = None,
        kroki: KrokiClient | None = None,
    ) -> None:
        self._writer = writer or ArtifactWriter()
        self._kroki = kroki or KrokiClient()

    def generate(
        self,
        graph: ProcessGraph,
        options: JobOptions,
        job_id: str,
    ) -> tuple[list[DiagramArtifact], list[str]]:
        """Return diagram artifacts and warnings. Never raises."""
        warnings: list[str] = []
        formats = set(options.diagram_formats or [])
        if not formats.intersection({"mermaid", "png"}):
            return [], warnings

        if not graph.nodes:
            warnings.append("Process graph is empty; skipping diagram generation.")
            return [], warnings

        export_mermaid = "mermaid" in formats
        export_png = "png" in formats
        requested = list(options.diagram_types or _DEFAULT_MERMAID_TYPES)
        artifacts: list[DiagramArtifact] = []

        for diagram_type in requested:
            if diagram_type not in _SUPPORTED_MERMAID_TYPES:
                warnings.append(
                    f"Diagram type {diagram_type!r} is not supported for Mermaid export; skipped."
                )
                continue

            renderer = _RENDERERS[diagram_type]
            try:
                content = renderer(graph)
            except MermaidRenderError as exc:
                warning = f"Mermaid {diagram_type} render failed: {exc}"
                _log.warning(warning)
                warnings.append(warning)
                continue

            if export_mermaid:
                filename = _MMD_FILENAMES[diagram_type]
                rel_path, checksum = self._writer.write_text(job_id, filename, content)
                artifacts.append(
                    DiagramArtifact(
                        path=rel_path,
                        type="diagram",
                        description=f"Process {diagram_type} (Mermaid)",
                        format="mermaid",
                        diagram_type=diagram_type,
                        mime_type="text/plain",
                        content=content,
                        checksum=checksum,
                    )
                )
                _log.info("Generated Mermaid %s diagram at %s", diagram_type, rel_path)

            if export_png:
                png_artifact, png_warning = self._export_mermaid_png(
                    content, diagram_type, job_id
                )
                if png_artifact is not None:
                    artifacts.append(png_artifact)
                elif png_warning:
                    warnings.append(png_warning)

        return artifacts, warnings

    def _export_mermaid_png(
        self,
        mermaid_source: str,
        diagram_type: DiagramType,
        job_id: str,
    ) -> tuple[DiagramArtifact | None, str | None]:
        """Convert Mermaid source to PNG via Kroki and save. Returns (artifact, warning)."""
        filename = _PNG_FILENAMES[diagram_type]
        try:
            rel_path, checksum = self._writer.save_mermaid_png(
                job_id,
                filename,
                mermaid_source,
                kroki=self._kroki,
            )
        except KrokiError as exc:
            warning = f"PNG export for {diagram_type} failed: {exc}"
            _log.warning(warning)
            return None, warning

        _log.info("Generated PNG %s diagram at %s", diagram_type, rel_path)
        return (
            DiagramArtifact(
                path=rel_path,
                type="diagram",
                description=f"Process {diagram_type} (PNG via Kroki)",
                format="png",
                diagram_type=diagram_type,
                mime_type="image/png",
                checksum=checksum,
            ),
            None,
        )
