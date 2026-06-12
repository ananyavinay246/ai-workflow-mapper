"""Automation Analyzer — graph heuristics, evidence, optional LLM enrichment."""

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
from ai_workflow_mapper.workflow.automation_heuristics import (
    candidates_to_opportunities,
    detect_automation_candidates,
)
from ai_workflow_mapper.workflow.domain import AutomationOpportunity, Evidence, JobOptions, ProcessGraph
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
You are a process automation analyst. Refine automation opportunity findings using ONLY the
provided graph-derived findings and document excerpts.

CRITICAL: If a heuristic opportunity is a false positive or the step is already automated
based on the documents, OMIT it from the final `automation_opportunities` array entirely.

Return raw JSON only (no markdown fences) matching this schema:
{schema_json}

Preserve each valid opportunity `id` exactly. Refine suggested_approach, time_savings_per_week,
roi, and effort. Only include evidence quotes that appear verbatim in the excerpts.
"""


def _build_enrichment_prompt(schema: dict) -> str:
    return _ENRICHMENT_PROMPT_TEMPLATE.replace(
        "{schema_json}", json.dumps(schema, indent=2)
    )


def _load_enrichment_schema() -> dict:
    return load_enrichment_schema(
        array_property="automation_opportunities",
        finding_def="automation_opportunity",
    )


def _wrap(text: str, source: str) -> str:
    return f"{_TRUST_OPEN}[source: {source}]\n{text}{_TRUST_CLOSE}"


class AutomationAnalyzer:
    """Detect automation opportunities from a ProcessGraph and attach evidence."""

    def __init__(self, adapter: LLMAdapterProtocol | None = None) -> None:
        self._adapter = adapter

    def analyze(
        self,
        graph: ProcessGraph,
        normalized: NormalizedInput,
        options: JobOptions,
        trace_id: str,
    ) -> tuple[list[AutomationOpportunity], list[dict], list[str]]:
        """Return (findings, citation dicts, warnings). Never raises."""
        warnings: list[str] = []
        candidates = detect_automation_candidates(graph)
        if not candidates:
            return [], [], warnings

        findings = candidates_to_opportunities(candidates)
        label_by_id = {c.node_id: c.label for c in candidates}

        enriched_findings: list[AutomationOpportunity] = []
        for finding in findings:
            node_id = finding.id.removeprefix("ao-")
            evidence, ev_warning = find_evidence(
                normalized,
                node_id=node_id,
                label=label_by_id.get(node_id, finding.name),
                finding_kind="automation",
            )
            if ev_warning:
                warnings.append(ev_warning.replace(f"ao-{node_id}", finding.id))
            enriched_findings.append(finding.model_copy(update={"evidence": evidence}))

        findings = enriched_findings

        if options.mode == "thorough" and self._adapter is not None and findings:
            findings, enrich_warnings = self._enrich_with_llm(
                findings, normalized, options, trace_id
            )
            warnings.extend(enrich_warnings)

        citations = _findings_to_citations(findings)
        _log.info(
            "Automation analysis complete [%s]: %d findings",
            trace_id,
            len(findings),
        )
        return findings, citations, warnings

    def _enrich_with_llm(
        self,
        findings: list[AutomationOpportunity],
        normalized: NormalizedInput,
        options: JobOptions,
        trace_id: str,
    ) -> tuple[list[AutomationOpportunity], list[str]]:
        warnings: list[str] = []
        try:
            schema = _load_enrichment_schema()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Automation LLM enrichment skipped: schema load failed: {exc}")
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
            f"Current automation opportunities (heuristic):\n{payload}\n\n"
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
                f"Automation LLM enrichment failed "
                f"({err.get('error_code', 'unknown')}): "
                f"{err.get('message', response.result)}. Using heuristic findings."
            )
            return findings, warnings

        raw_list = response.result.get("structured_object", {}).get("automation_opportunities", [])
        by_id = {f.id: f for f in findings}
        enriched: list[AutomationOpportunity] = []

        for item in raw_list:
            fid = item.get("id")
            if not fid or fid not in by_id:
                continue
            base = by_id[fid]
            llm_evidence = [
                Evidence.model_validate(e) for e in item.get("evidence", [])
            ]
            evidence = (
                filter_grounded_evidence(llm_evidence, normalized)
                if llm_evidence
                else base.evidence
            )
            if not evidence:
                evidence = base.evidence
            try:
                enriched.append(
                    AutomationOpportunity(
                        id=fid,
                        name=item.get("name") or base.name,
                        effort=item.get("effort") or base.effort,
                        roi=item.get("roi") or base.roi,
                        priority=item.get("priority") or base.priority,
                        time_savings_per_week=item.get("time_savings_per_week")
                        or base.time_savings_per_week,
                        suggested_approach=item.get("suggested_approach")
                        or base.suggested_approach,
                        evidence=evidence,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Could not parse enriched automation opportunity {fid}: {exc}")
                enriched.append(base)

        if not enriched and findings:
            _log.warning(
                "LLM returned 0 automation opportunities. Falling back to heuristic findings."
            )
            return findings, warnings

        return enriched, warnings


def _findings_to_citations(findings: list[AutomationOpportunity]) -> list[dict]:
    citations: list[dict] = []
    for finding in findings:
        node_id = finding.id.removeprefix("ao-")
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
