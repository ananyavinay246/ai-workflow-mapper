"""Tests for Mermaid diagram generator."""

import json
from pathlib import Path

import jsonschema
import pytest

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
