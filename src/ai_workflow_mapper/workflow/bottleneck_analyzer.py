"""Bottleneck Analyzer — graph heuristics, evidence, optional LLM enrichment."""

from __future__ import annotations

import json
import logging
import uuid

from ai_workflow_mapper.platform.contracts.llm_adapter import (
    LLMAdapterContext,
    LLMAdapterOperation,
    LLMAdapterProtocol,
    LLMAdapterRequest,
    LLMAdapterStatus,
)
from ai_workflow_mapper.workflow.analysis_enrichment_schema import load_enrichment_schema
from ai_workflow_mapper.workflow.bottleneck_heuristics import (
    candidate_to_finding,
    detect_bottleneck_candidates,
)
from ai_workflow_mapper.workflow.domain import (
    BottleneckFinding,
    Evidence,
    JobOptions,
    ProcessGraph,
)
from ai_workflow_mapper.workflow.evidence_matcher import (
    filter_grounded_evidence,
    find_evidence,
)
from ai_workflow_mapper.workflow.extractor import _TRUST_CLOSE, _TRUST_OPEN
from ai_workflow_mapper.workflow.normalizer import NormalizedInput

_log = logging.getLogger(__name__)

_SYSTEM_CTX = LLMAdapterContext(
    actor_id="system",
    tenant_id="system",
    environment="local",
)

_ENRICHMENT_PROMPT_TEMPLATE = """\
You are a process improvement analyst. Refine bottleneck findings using ONLY the
provided graph-derived findings and document excerpts.

CRITICAL: If a heuristic bottleneck finding is a false positive (e.g., it is fully 
automated, instantaneous, or not an actual constraint based on the documents), 
OMIT it from the final `bottlenecks` array entirely.

Return raw JSON only (no markdown fences) matching this schema:
{schema_json}

Preserve each valid bottleneck `id` exactly. Improve description, impact, and
root_cause_hypothesis. Only include evidence quotes that appear verbatim in the excerpts.
"""


def _build_enrichment_prompt(schema: dict) -> str:
    return _ENRICHMENT_PROMPT_TEMPLATE.replace(
        "{schema_json}", json.dumps(schema, indent=2)
    )


def _load_enrichment_schema() -> dict:
    return load_enrichment_schema(array_property="bottlenecks", finding_def="bottleneck")


def _wrap(text: str, source: str) -> str:
    return f"{_TRUST_OPEN}[source: {source}]\n{text}{_TRUST_CLOSE}"


class BottleneckAnalyzer:
    """Detect bottlenecks from a ProcessGraph and attach evidence."""

    def __init__(self, adapter: LLMAdapterProtocol | None = None) -> None:
        self._adapter = adapter

    def analyze(
        self,
        graph: ProcessGraph,
        normalized: NormalizedInput,
        options: JobOptions,
        trace_id: str,
    ) -> tuple[list[BottleneckFinding], list[dict], list[str]]:
        """Return (findings, citation dicts, warnings). Never raises."""
        warnings: list[str] = []
        candidates = detect_bottleneck_candidates(graph)
        if not candidates:
            return [], [], warnings

        findings: list[BottleneckFinding] = []
        for candidate in candidates:
            finding = candidate_to_finding(candidate)
            evidence, ev_warning = find_evidence(
                normalized, node_id=candidate.node_id, label=candidate.label
            )
            if ev_warning:
                warnings.append(ev_warning)
            finding = finding.model_copy(update={"evidence": evidence})
            findings.append(finding)

        if options.mode == "thorough" and self._adapter is not None and findings:
            findings, enrich_warnings = self._enrich_with_llm(
                findings, normalized, options, trace_id
            )
            warnings.extend(enrich_warnings)

        citations = _findings_to_citations(findings)
        _log.info(
            "Bottleneck analysis complete [%s]: %d findings",
            trace_id,
            len(findings),
        )
        return findings, citations, warnings

    def _enrich_with_llm(
        self,
        findings: list[BottleneckFinding],
        normalized: NormalizedInput,
        options: JobOptions,
        trace_id: str,
    ) -> tuple[list[BottleneckFinding], list[str]]:
        warnings: list[str] = []
        try:
            schema = _load_enrichment_schema()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Bottleneck LLM enrichment skipped: schema load failed: {exc}")
            return findings, warnings

        excerpts = "\n\n".join(
            _wrap(doc.text[:4000], doc.filename)
            for doc in normalized.documents
            if doc.char_count > 0
        )
        payload = json.dumps(
            [f.model_dump(mode="json", exclude_none=True) for f in findings],
            indent=2,
        )
        user_content = (
            f"Current bottleneck findings (heuristic):\n{payload}\n\n"
            f"{excerpts if excerpts else _wrap('No excerpts available.', 'documents')}"
        )

        cost_limit = options.max_cost_usd if options.max_cost_usd is not None else 0.5
        request = LLMAdapterRequest(
            request_id=str(uuid.uuid4()),
            operation=LLMAdapterOperation.complete_structured,
            input={
                "system": _build_enrichment_prompt(schema),
                "messages": [{"role": "user", "content": user_content}],
                "output_schema": schema,
                "max_tokens": 4096,
                "cost_limit_usd": cost_limit,
            },
            context=_SYSTEM_CTX,
            trace_id=trace_id,
        )

        response = self._adapter.handle(request)
        if response.status != LLMAdapterStatus.succeeded:
            err = response.result.get("error", {})
            warnings.append(
                f"Bottleneck LLM enrichment failed "
                f"({err.get('error_code', 'unknown')}): "
                f"{err.get('message', response.result)}. Using heuristic findings."
            )
            return findings, warnings

        raw_list = response.result.get("structured_object", {}).get("bottlenecks", [])
        by_id = {f.id: f for f in findings}
        enriched: list[BottleneckFinding] = []

        for item in raw_list:
            fid = item.get("id")
            if not fid or fid not in by_id:
                continue
            base = by_id[fid]
            llm_evidence = [
                Evidence.model_validate(e) for e in item.get("evidence", [])
            ]
            evidence = filter_grounded_evidence(llm_evidence, normalized) if llm_evidence else base.evidence
            if not evidence:
                evidence = base.evidence
            try:
                enriched.append(
                    BottleneckFinding(
                        id=fid,
                        name=item.get("name") or base.name,
                        severity=item.get("severity") or base.severity,
                        description=item.get("description") or base.description,
                        impact=item.get("impact") or base.impact,
                        root_cause_hypothesis=item.get("root_cause_hypothesis")
                        or base.root_cause_hypothesis,
                        evidence=evidence,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Could not parse enriched bottleneck {fid}: {exc}")
                enriched.append(base)

        if not enriched and findings:
            _log.warning("LLM returned 0 bottlenecks. Falling back to all heuristic findings.")
            return findings, warnings

        return enriched, warnings


def _findings_to_citations(findings: list[BottleneckFinding]) -> list[dict]:
    citations: list[dict] = []
    for finding in findings:
        node_id = finding.id.removeprefix("bn-")
        for ev in finding.evidence:
            citations.append(
                {
                    "source_filename": ev.source_filename,
                    "quote": ev.quote,
                    "trust_level": "untrusted",
                    "char_start": ev.char_start,
                    "char_end": ev.char_end,
                    "node_id": node_id,
                    "finding_id": finding.id,
                }
            )
    return citations
