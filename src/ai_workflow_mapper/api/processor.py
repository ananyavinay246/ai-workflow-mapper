"""Job processor — wires the workflow pipeline into the API layer."""

import os
from typing import Any

from ai_workflow_mapper.platform.contracts.document_loader import DocumentLoaderConfig
from ai_workflow_mapper.platform.contracts.llm_adapter import LLMAdapterConfig, LLMAdapterContext
from ai_workflow_mapper.platform.local.document_loader import LocalDocumentLoader
from ai_workflow_mapper.platform.local.llm_adapter import LocalLLMAdapter
from ai_workflow_mapper.workflow.domain import NormalizationSummary, SkippedDocument, WorkflowResult
from ai_workflow_mapper.workflow.extractor import ProcessExtractor
from ai_workflow_mapper.workflow.graph_builder import ProcessGraphBuilder
from ai_workflow_mapper.workflow.normalizer import InputNormalizer

from .models import JobInput

_SYSTEM_CTX = LLMAdapterContext(
    actor_id="system",
    tenant_id="system",
    environment="local",
)


def _build_llm_adapter(job_input: JobInput) -> LocalLLMAdapter | None:
    """Return a LocalLLMAdapter when LLM_API_KEY is available, else None."""
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        return None

    settings: dict[str, Any] = {}
    if job_input.options.max_cost_usd is not None:
        settings["cost_limit_usd"] = job_input.options.max_cost_usd
    else:
        settings["cost_limit_usd"] = 0.5
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


def process(job_input: JobInput) -> dict[str, Any]:
    """Run the workflow pipeline: normalize → extract → build graph."""
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
        process_graph = ProcessGraphBuilder().build(extraction)
    else:
        summary.warnings.append(
            "LLM_API_KEY not set; skipping process extraction and graph build."
        )

    result = WorkflowResult(
        normalization_summary=summary,
        process_graph=process_graph if process_graph and process_graph.nodes else None,
    )
    return result.model_dump(mode="json", exclude_none=True)
