"""Input Normalizer — extracts text from all supported input formats.

Tier 1 (delegated to document_loader): .txt, .md, .json, .pdf, .docx
Tier 3 (deferred):                     URLs, unsupported extensions → skip + warning
"""

import base64
import csv
import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_workflow_mapper.platform.contracts.document_loader import (
    DocumentLoaderContext,
    DocumentLoaderOperation,
    DocumentLoaderProtocol,
    DocumentLoaderRequest,
)

from .domain import InputDocument, WorkflowInput
from .text_cleaner import clean_extracted_text


_LOADER_EXTENSIONS = frozenset({".txt", ".md", ".json", ".pdf", ".docx"})

_SYSTEM_CTX = DocumentLoaderContext(
    actor_id="system",
    tenant_id="system",
    environment="local",
)


class UnsupportedSourceError(Exception):
    pass


@dataclass
class NormalizedDocument:
    filename: str
    text: str
    source_type: str
    char_count: int
    parser: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedInput:
    documents: list[NormalizedDocument] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class InputNormalizer:
    def __init__(self, loader: DocumentLoaderProtocol) -> None:
        self._loader = loader

    def normalize(self, workflow_input: WorkflowInput, trace_id: str) -> NormalizedInput:
        result = NormalizedInput()
        for i, doc in enumerate(workflow_input.documents):
            req_trace = f"{trace_id}-norm-{i}"
            try:
                norm_doc = self._route(doc, req_trace)
                result.documents.append(norm_doc)
                for w in norm_doc.warnings:
                    result.warnings.append(f"[{doc.filename}] {w}")
            except UnsupportedSourceError as exc:
                result.skipped.append({"filename": doc.filename, "reason": str(exc)})
                result.warnings.append(f"[{doc.filename}] skipped: {exc}")
            except Exception as exc:  # noqa: BLE001
                result.skipped.append({"filename": doc.filename, "reason": str(exc)})
                result.warnings.append(f"[{doc.filename}] parse error: {exc}")
        return result

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _route(self, doc: InputDocument, trace_id: str) -> NormalizedDocument:
        if doc.filename.startswith(("http://", "https://")):
            raise UnsupportedSourceError("URL ingestion not yet supported")
        ext = Path(doc.filename).suffix.lower()
        if ext in _LOADER_EXTENSIONS:
            return self._extract_via_loader(doc, trace_id)
        raise UnsupportedSourceError(f"Unsupported format: {ext!r}")

    # ------------------------------------------------------------------
    # Tier 1 — document_loader
    # ------------------------------------------------------------------

    def _extract_via_loader(self, doc: InputDocument, trace_id: str) -> NormalizedDocument:
        req = DocumentLoaderRequest(
            request_id=trace_id,
            operation=DocumentLoaderOperation.extract_text,
            input={"filename": doc.filename, "content_bytes_b64": doc.content_b64},
            context=_SYSTEM_CTX,
            trace_id=trace_id,
        )
        resp = self._loader.handle(req)
        if resp.status.value == "failed":
            err = resp.result.get("error", {})
            raise RuntimeError(err.get("message", "document_loader failed"))
        text = resp.result.get("text", "")
        parser = resp.result.get("parser", "unknown")
        extra_meta = {k: v for k, v in resp.result.items() if k not in {"text", "char_count", "parser"}}
        warnings = list(resp.warnings)

        cleaned = clean_extracted_text(text, parser=parser, filename=doc.filename)
        text = cleaned.text
        warnings.extend(cleaned.warnings)
        if cleaned.stats:
            extra_meta["cleaning"] = cleaned.stats

        return NormalizedDocument(
            filename=doc.filename,
            text=text,
            source_type=doc.source_type,
            char_count=len(text),
            parser=parser,
            warnings=warnings,
            metadata=extra_meta,
        )
