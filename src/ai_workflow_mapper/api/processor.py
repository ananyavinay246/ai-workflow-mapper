"""Job processor — wires the workflow pipeline into the API layer."""

import os
from dataclasses import dataclass, field
from typing import Any

from ai_workflow_mapper.platform.contracts.document_loader import DocumentLoaderConfig
from ai_workflow_mapper.platform.contracts.llm_adapter import LLMAdapterConfig, LLMAdapterContext
from ai_workflow_mapper.platform.local.document_loader import LocalDocumentLoader
from ai_workflow_mapper.platform.local.llm_adapter import LocalLLMAdapter
from ai_workflow_mapper.workflow.bottleneck_analyzer import BottleneckAnalyzer
from ai_workflow_mapper.workflow.diagram_generator import MermaidDiagramGenerator
from ai_workflow_mapper.workflow.domain import (
    AnalysisFindings,
    NormalizationSummary,
    SkippedDocument,
    WorkflowResult,
)
from ai_workflow_mapper.workflow.extractor import ProcessExtractor
from ai_workflow_mapper.workflow.graph_builder import ProcessGraphBuilder
from ai_workflow_mapper.workflow.normalizer import InputNormalizer
from ai_workflow_mapper.workflow.automation_analyzer import AutomationAnalyzer
from ai_workflow_mapper.workflow.redundancy_analyzer import RedundancyAnalyzer

from .models import JobInput

_SYSTEM_CTX = LLMAdapterContext(
    actor_id="system",
    tenant_id="system",
    environment="local",
)


@dataclass
class JobProcessResult:
    result: dict[str, Any]
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _build_llm_adapter(job_input: JobInput) -> LocalLLMAdapter | None:
    """Return a LocalLLMAdapter when LLM_API_KEY is available, else None."""
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        return None

    settings: dict[str, Any] = {}
    if job_input.options.max_cost_usd is not None:
        settings["cost_limit_usd"] = job_input.options.max_cost_usd
    else:
        settings["cost_limit_usd"] = 1.0
    if job_input.options.model_profile:
        settings["model_id"] = job_input.options.model_profile

    return LocalLLMAdapter(
        LLMAdapterConfig(
            environment="local",
            implementation="local",
            settings=settings,
            security={},
        )
    )


def process(job_input: JobInput) -> JobProcessResult:
    """Run the workflow pipeline: normalize → extract → build graph → diagrams."""
    from ai_workflow_mapper.platform.env_loader import load_project_env

    load_project_env()
    loader = LocalDocumentLoader(
        DocumentLoaderConfig(
            environment="local",
            implementation="local",
            settings={},
            security={},
        )
    )
    normalized = InputNormalizer(loader).normalize(
        job_input.input, trace_id=job_input.request_id
    )

    summary = NormalizationSummary(
        normalized_documents=len(normalized.documents),
        skipped_documents=len(normalized.skipped),
        skipped=[SkippedDocument(**s) for s in normalized.skipped],
        warnings=list(normalized.warnings),
    )

    llm_adapter = _build_llm_adapter(job_input)

    process_graph = None
    if llm_adapter is not None:
        extraction = ProcessExtractor(llm_adapter, job_input.options).extract(
            normalized,
            trace_id=job_input.request_id,
            description=job_input.input.description,
        )
        for w in extraction.warnings:
            summary.warnings.append(w)
        built = ProcessGraphBuilder().build(extraction)
        process_graph = built if built.nodes else None
    else:
        summary.warnings.append(
            "LLM_API_KEY not set; skipping process extraction and graph build."
        )

    analysis: AnalysisFindings | None = None
    citations: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    job_warnings: list[str] = []

    if process_graph is not None:
        bn_findings, bn_citations, bn_warnings = BottleneckAnalyzer(llm_adapter).analyze(
            process_graph,
            normalized,
            job_input.options,
            trace_id=job_input.request_id,
        )
        rd_findings, rd_citations, rd_warnings = RedundancyAnalyzer(llm_adapter).analyze(
            process_graph,
            normalized,
            job_input.options,
            trace_id=job_input.request_id,
        )
        ao_findings, ao_citations, ao_warnings = AutomationAnalyzer(llm_adapter).analyze(
            process_graph,
            normalized,
            job_input.options,
            trace_id=job_input.request_id,
        )
        job_warnings.extend(bn_warnings)
        job_warnings.extend(rd_warnings)
        job_warnings.extend(ao_warnings)

        analysis_fields: dict[str, Any] = {}
        if bn_findings:
            analysis_fields["bottlenecks"] = bn_findings
        if rd_findings:
            analysis_fields["redundancies"] = rd_findings
        if ao_findings:
            analysis_fields["automation_opportunities"] = ao_findings
        else:
            job_warnings.append("No high-confidence automation opportunities found.")
        if analysis_fields:
            analysis = AnalysisFindings(**analysis_fields)

        citations = bn_citations + rd_citations + ao_citations

        diagram_artifacts, diagram_warnings = MermaidDiagramGenerator().generate(
            process_graph,
            job_input.options,
            job_input.request_id,
        )
        artifacts = [a.model_dump(mode="json", exclude_none=True) for a in diagram_artifacts]
        job_warnings.extend(diagram_warnings)

    result = WorkflowResult(
        normalization_summary=summary,
        process_graph=process_graph,
        analysis=analysis,
    )
    result_dict = result.model_dump(mode="json", exclude_none=True, by_alias=True)
    if result_dict.get("analysis"):
        result_dict["analysis"] = {
            k: v for k, v in result_dict["analysis"].items() if v
        }

    return JobProcessResult(
        result=result_dict,
        artifacts=artifacts,
        citations=citations,
        warnings=job_warnings,
    )
