"""Domain Pydantic models matching schemas/workflow_input.schema.json, job_options.schema.json,
process_extraction.schema.json, process_graph.schema.json, and workflow_result.schema.json."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input / options
# ---------------------------------------------------------------------------

SourceType = Literal["document", "interview", "sop", "diagram", "tool_export"]
OutputFormat = Literal["json", "markdown", "docx", "pdf"]
JobMode = Literal["standard", "fast", "thorough"]
DiagramType = Literal["flowchart", "swimlane", "value_stream", "entity_relationship"]
DiagramFormat = Literal["mermaid", "bpmn_xml", "drawio_xml", "svg", "png"]


class InputDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    content_b64: str = Field(min_length=1)
    source_type: SourceType = "document"


class WorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[InputDocument] = Field(default_factory=list)
    description: str | None = None


class JobOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_format: OutputFormat = "json"
    mode: JobMode = "standard"
    diagram_types: list[DiagramType] | None = None
    diagram_formats: list[DiagramFormat] | None = None
    model_profile: str | None = None
    max_cost_usd: float | None = Field(default=None, ge=0)
    require_human_review: bool = False


# ---------------------------------------------------------------------------
# Process extraction (LLM raw output — matches process_extraction.schema.json)
# ---------------------------------------------------------------------------

class ExtractedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    actor: str | None = None
    tool: str | None = None
    duration: str | None = None
    frequency: str | None = None
    sequence_order: int | None = Field(default=None, ge=0)
    uncertain: bool = False


class Handoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_step_id: str = Field(min_length=1)
    to_step_id: str = Field(min_length=1)
    from_actor: str | None = None
    to_actor: str | None = None


class DecisionPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    true_branch_step_id: str | None = None
    false_branch_step_id: str | None = None


class ProcessExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[ExtractedStep] = Field(default_factory=list)
    handoffs: list[Handoff] = Field(default_factory=list)
    decision_points: list[DecisionPoint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Process graph (canonical model — matches process_graph.schema.json)
# ---------------------------------------------------------------------------

NodeType = Literal["task", "decision", "start", "end", "handoff"]
ActorKind = Literal["role", "department", "system"]


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: NodeType
    label: str = Field(min_length=1)
    actor_id: str | None = None
    tool: str | None = None
    duration: str | None = None
    frequency: str | None = None
    metadata: dict | None = None


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)
    label: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: ActorKind = "role"


class Swimlane(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1)
    node_ids: list[str] = Field(default_factory=list)


class ProcessGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"] = "1.0"
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    actors: list[Actor] = Field(default_factory=list)
    swimlanes: list[Swimlane] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization summary / workflow result
# ---------------------------------------------------------------------------

class SkippedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class NormalizationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_documents: int = Field(ge=0)
    skipped_documents: int = Field(ge=0)
    skipped: list[SkippedDocument] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalization_summary: NormalizationSummary
    process_graph: ProcessGraph | None = None
    analysis: dict | None = None


# ---------------------------------------------------------------------------
# Diagram artifact (matches diagram_artifact.schema.json)
# ---------------------------------------------------------------------------

ArtifactFormat = Literal["mermaid", "bpmn_xml", "drawio_xml", "svg", "png", "markdown", "docx", "pdf"]


class DiagramArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    type: str = Field(min_length=1)
    description: str | None = None
    format: ArtifactFormat | None = None
    diagram_type: DiagramType | None = None
    mime_type: str | None = None
    storage_uri: str | None = None
    content: str | None = None
    checksum: str | None = None
