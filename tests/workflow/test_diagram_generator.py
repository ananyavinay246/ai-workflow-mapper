"""Tests for Mermaid diagram generator."""

import json
from pathlib import Path

import jsonschema
import pytest
from unittest.mock import patch

from ai_workflow_mapper.workflow.diagram_generator import MermaidDiagramGenerator
from ai_workflow_mapper.workflow.domain import JobOptions, ProcessGraph

SCHEMAS_DIR = Path(__file__).parents[2] / "schemas"
FIXTURE = Path(__file__).parents[2] / "fixtures" / "diagrams" / "sample_process_graph.json"


def _schema_store() -> dict:
    store: dict = {}
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        store[data["$id"]] = data
    return store


def _validate_artifact(artifact: dict) -> None:
    schema = json.loads((SCHEMAS_DIR / "diagram_artifact.schema.json").read_text(encoding="utf-8"))
    resolver = jsonschema.RefResolver(base_uri=schema["$id"], referrer=schema, store=_schema_store())
    jsonschema.validate(artifact, schema, resolver=resolver)


@pytest.fixture
def sample_graph() -> ProcessGraph:
    return ProcessGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_no_diagram_formats_returns_empty(sample_graph: ProcessGraph):
    artifacts, warnings = MermaidDiagramGenerator().generate(
        sample_graph, JobOptions(), "job-001"
    )
    assert artifacts == []
    assert warnings == []


def test_mermaid_enabled_generates_flowchart_and_swimlane(
    sample_graph: ProcessGraph, tmp_path: Path
):
    from ai_workflow_mapper.platform.local.artifact_writer import ArtifactWriter

    gen = MermaidDiagramGenerator(writer=ArtifactWriter(tmp_path / "artifacts"))
    artifacts, warnings = gen.generate(
        sample_graph,
        JobOptions(diagram_formats=["mermaid"]),
        "job-002",
    )
    assert warnings == []
    assert len(artifacts) == 2
    types = {a.diagram_type for a in artifacts}
    assert types == {"flowchart", "swimlane"}
    for artifact in artifacts:
        dumped = artifact.model_dump(mode="json", exclude_none=True)
        _validate_artifact(dumped)
        assert artifact.format == "mermaid"
        assert artifact.type == "diagram"
        assert artifact.content
        assert artifact.checksum.startswith("sha256:")
        assert (tmp_path / artifact.path).is_file()


def test_flowchart_only_option(sample_graph: ProcessGraph, tmp_path: Path):
    from ai_workflow_mapper.platform.local.artifact_writer import ArtifactWriter

    gen = MermaidDiagramGenerator(writer=ArtifactWriter(tmp_path / "artifacts"))
    artifacts, _ = gen.generate(
        sample_graph,
        JobOptions(diagram_formats=["mermaid"], diagram_types=["flowchart"]),
        "job-003",
    )
    assert len(artifacts) == 1
    assert artifacts[0].diagram_type == "flowchart"


def test_unsupported_diagram_type_warns(sample_graph: ProcessGraph):
    artifacts, warnings = MermaidDiagramGenerator().generate(
        sample_graph,
        JobOptions(
            diagram_formats=["mermaid"],
            diagram_types=["flowchart", "value_stream"],
        ),
        "job-004",
    )
    assert len(artifacts) == 1
    assert any("value_stream" in w for w in warnings)


def test_empty_graph_warns():
    artifacts, warnings = MermaidDiagramGenerator().generate(
        ProcessGraph(),
        JobOptions(diagram_formats=["mermaid"]),
        "job-005",
    )
    assert artifacts == []
    assert any("empty" in w.lower() for w in warnings)


def test_png_export_via_kroki(sample_graph: ProcessGraph, tmp_path: Path):
    from ai_workflow_mapper.platform.local.artifact_writer import ArtifactWriter
    from ai_workflow_mapper.platform.local.kroki_client import KrokiClient

    fake_kroki = KrokiClient(base_url="https://kroki.example")
    fake_png = b"\x89PNG\r\n\x1a\npng"

    with patch.object(fake_kroki, "mermaid_to_png", return_value=fake_png):
        gen = MermaidDiagramGenerator(
            writer=ArtifactWriter(tmp_path / "artifacts"),
            kroki=fake_kroki,
        )
        artifacts, warnings = gen.generate(
            sample_graph,
            JobOptions(diagram_formats=["mermaid", "png"], diagram_types=["flowchart"]),
            "job-006",
        )

    assert warnings == []
    assert len(artifacts) == 2
    formats = {a.format for a in artifacts}
    assert formats == {"mermaid", "png"}
    png = next(a for a in artifacts if a.format == "png")
    assert png.path.endswith("flowchart.png")
    assert png.mime_type == "image/png"
    assert (tmp_path / png.path).read_bytes() == fake_png


def test_png_only_still_renders_mermaid_source(sample_graph: ProcessGraph, tmp_path: Path):
    from ai_workflow_mapper.platform.local.artifact_writer import ArtifactWriter
    from ai_workflow_mapper.platform.local.kroki_client import KrokiClient

    fake_kroki = KrokiClient(base_url="https://kroki.example")
    with patch.object(fake_kroki, "mermaid_to_png", return_value=b"\x89PNG"):
        gen = MermaidDiagramGenerator(
            writer=ArtifactWriter(tmp_path / "artifacts"),
            kroki=fake_kroki,
        )
        artifacts, _ = gen.generate(
            sample_graph,
            JobOptions(diagram_formats=["png"], diagram_types=["flowchart"]),
            "job-007",
        )
    assert len(artifacts) == 1
    assert artifacts[0].format == "png"


def test_kroki_failure_adds_warning_not_raises(sample_graph: ProcessGraph, tmp_path: Path):
    from ai_workflow_mapper.platform.local.artifact_writer import ArtifactWriter
    from ai_workflow_mapper.platform.local.kroki_client import KrokiClient, KrokiError

    fake_kroki = KrokiClient(base_url="https://kroki.example")
    with patch.object(
        fake_kroki, "mermaid_to_png", side_effect=KrokiError("Syntax error")
    ):
        gen = MermaidDiagramGenerator(
            writer=ArtifactWriter(tmp_path / "artifacts"),
            kroki=fake_kroki,
        )
        artifacts, warnings = gen.generate(
            sample_graph,
            JobOptions(diagram_formats=["mermaid", "png"], diagram_types=["flowchart"]),
            "job-008",
        )

    assert len(artifacts) == 1
    assert artifacts[0].format == "mermaid"
    assert any("PNG export" in w for w in warnings)
