"""Tests for self-contained LLM enrichment schemas (no RefResolver)."""

import jsonschema

from ai_workflow_mapper.workflow.analysis_enrichment_schema import load_enrichment_schema
from ai_workflow_mapper.workflow.automation_analyzer import _load_enrichment_schema as load_ao_schema
from ai_workflow_mapper.workflow.bottleneck_analyzer import _load_enrichment_schema as load_bn_schema
from ai_workflow_mapper.workflow.redundancy_analyzer import _load_enrichment_schema as load_rd_schema


def _assert_schema_resolves(schema: dict, sample: dict) -> None:
    jsonschema.validate(sample, schema)


def test_bottleneck_enrichment_schema_resolves_evidence_ref():
    schema = load_bn_schema()
    sample = {
        "bottlenecks": [
            {
                "id": "bn-step_1",
                "name": "Manual approval",
                "severity": "Moderate",
                "description": "Slow review step.",
                "evidence": [
                    {
                        "quote": "Manager must approve within 24 hours.",
                        "source_filename": "sop.pdf",
                    }
                ],
            }
        ]
    }
    _assert_schema_resolves(schema, sample)


def test_redundancy_enrichment_schema_resolves_evidence_ref():
    schema = load_rd_schema()
    sample = {
        "redundancies": [
            {
                "id": "rd-dup-s1-s2",
                "name": "Duplicate entry",
                "description": "Same data entered twice.",
                "evidence": [
                    {
                        "quote": "Re-enter order in CRM.",
                        "source_filename": "sop.pdf",
                    }
                ],
            }
        ]
    }
    _assert_schema_resolves(schema, sample)


def test_automation_enrichment_schema_resolves_evidence_ref():
    schema = load_ao_schema()
    sample = {
        "automation_opportunities": [
            {
                "id": "ao-step_1",
                "name": "Send confirmation email",
                "effort": "Low",
                "evidence": [
                    {
                        "quote": "Email the customer confirmation.",
                        "source_filename": "sop.pdf",
                    }
                ],
            }
        ]
    }
    _assert_schema_resolves(schema, sample)


def test_load_enrichment_schema_includes_evidence_defs():
    schema = load_enrichment_schema(array_property="bottlenecks", finding_def="bottleneck")
    assert "evidence" in schema["$defs"]
    assert schema["$defs"]["evidence"]["required"] == ["quote", "source_filename"]
