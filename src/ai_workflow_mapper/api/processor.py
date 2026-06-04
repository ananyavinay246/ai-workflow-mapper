"""Job processor — wires the workflow pipeline into the API layer."""

from typing import Any

from ai_workflow_mapper.platform.contracts.document_loader import DocumentLoaderConfig
from ai_workflow_mapper.platform.local.document_loader import LocalDocumentLoader
from ai_workflow_mapper.workflow.domain import WorkflowInput
from ai_workflow_mapper.workflow.normalizer import InputNormalizer

from .models import JobInput


def process(job_input: JobInput) -> dict[str, Any]:
    """Normalize the caller's input documents.

    Next slice: pass normalized documents to the Process Extractor.
    """
    workflow_input = WorkflowInput.model_validate(job_input.input)
    loader = LocalDocumentLoader(
        DocumentLoaderConfig(
            environment="local",
            implementation="local",
            settings={},
            security={},
        )
    )
    result = InputNormalizer(loader).normalize(workflow_input, trace_id=job_input.request_id)
    return {
        "normalized_documents": len(result.documents),
        "skipped_documents": len(result.skipped),
        "skipped": result.skipped,
        "warnings": result.warnings,
    }
