"""Diagram generator — converts ProcessGraph into export artifacts."""

from __future__ import annotations

import logging

from ai_workflow_mapper.platform.local.artifact_writer import ArtifactWriter
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

_FILENAMES = {
    "flowchart": "flowchart.mmd",
    "swimlane": "swimlane.mmd",
}


class MermaidDiagramGenerator:
    """Generate Mermaid diagram artifacts from a ProcessGraph."""

    def __init__(self, writer: ArtifactWriter | None = None) -> None:
        self._writer = writer or ArtifactWriter()

    def generate(
        self,
        graph: ProcessGraph,
        options: JobOptions,
        job_id: str,
    ) -> tuple[list[DiagramArtifact], list[str]]:
        """Return diagram artifacts and warnings. Never raises."""
        warnings: list[str] = []
        formats = options.diagram_formats or []
        if "mermaid" not in formats:
            return [], warnings

        if not graph.nodes:
            warnings.append("Process graph is empty; skipping diagram generation.")
            return [], warnings

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

            filename = _FILENAMES[diagram_type]
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

        return artifacts, warnings
