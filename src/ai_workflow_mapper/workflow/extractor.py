"""Process Extractor — converts normalized text documents into a ProcessExtraction via LLM."""

import json
import logging
import uuid
from pathlib import Path

from ai_workflow_mapper.platform.contracts.llm_adapter import (
    LLMAdapterContext,
    LLMAdapterOperation,
    LLMAdapterProtocol,
    LLMAdapterRequest,
    LLMAdapterStatus,
)
from ai_workflow_mapper.workflow.domain import (
    DecisionPoint,
    ExtractedStep,
    Handoff,
    JobOptions,
    ProcessExtraction,
)
from ai_workflow_mapper.workflow.normalizer import NormalizedInput

_log = logging.getLogger(__name__)

_TRUST_OPEN = '<process_content trust_level="untrusted">'
_TRUST_CLOSE = "</process_content>"

_SCHEMAS_DIR = Path(__file__).parents[3] / "schemas"

# Default cost limit for multi-document corpora.  The LLM adapter's own
# default is $1.00 which is too low for a 20-document corpus.  Callers can
# override via JobOptions.max_cost_usd.
_DEFAULT_COST_LIMIT_USD = 0.5

_SYSTEM_PROMPT_TEMPLATE = """\
# Process Extraction System Prompt

```
You are an expert Business Process Analyst. Your task is to read a Standard Operating
Procedure (SOP) document and extract a structured, end-to-end business workflow from it.

---

## Extraction Rules

**Steps**
- Break the process into atomic steps. If a sentence describes two actions
  ("the manager reviews and signs"), produce two separate steps.
- Every step must have an explicit actor — the role, department, or system
  performing the action. If the document uses passive voice ("a notification is
  sent"), infer the responsible actor from context or label it explicitly
  (e.g. "Notification System"). Never leave actor blank.
- Assign each step a sequence_order integer starting from 0.
- If you are uncertain whether a step exists or what it means, set
  uncertain: true on that step and add a human-readable explanation to warnings.

**Handoffs**
- Record a handoff whenever responsibility transfers from one actor to another
  between two consecutive steps.
- Populate from_actor and to_actor where the actor names are known.

**Decision Points**
- Record a decision point whenever the process branches conditionally
  (approvals, rejections, routing logic, IF/THEN/ELSE).
- The condition field should be a plain-language question (e.g. "Is the order
  approved?").
- Set true_branch_step_id and false_branch_step_id to the step IDs the process
  routes to on each outcome. Omit either field if that branch is not described.

**Warnings**
- Use the warnings array to flag anything ambiguous, missing, or assumed —
  for example: "Step 4 actor inferred as Finance Team based on context."

---

## Output Format

Return a single JSON object that strictly conforms to the schema below.
No preamble, no explanation, no markdown fences — only the JSON object.

```json
{schema_json}
```

---

## Example

**Input SOP snippet:**
"The Customer Support Agent receives the service request ticket. If it is a
billing issue, the agent assigns the ticket to the Finance Team. Finance then
reviews the account within 24 hours."

**Correct output:**

```json
{
  "steps": [
    {
      "id": "step_1",
      "label": "Receive service request ticket",
      "actor": "Customer Support Agent",
      "sequence_order": 0
    },
    {
      "id": "step_2",
      "label": "Assign billing ticket to Finance Team queue",
      "actor": "Customer Support Agent",
      "sequence_order": 1
    },
    {
      "id": "step_3",
      "label": "Review customer account within 24-hour SLA",
      "actor": "Finance Team",
      "duration": "24 hours",
      "sequence_order": 2
    }
  ],
  "handoffs": [
    {
      "from_step_id": "step_2",
      "to_step_id": "step_3",
      "from_actor": "Customer Support Agent",
      "to_actor": "Finance Team"
    }
  ],
  "decision_points": [
    {
      "step_id": "step_1",
      "condition": "Is the issue type Billing?",
      "true_branch_step_id": "step_2"
    }
  ],
  "warnings": []
}
```

Notice:
- Step IDs are stable strings used as references in handoffs and decision_points.
- The decision point lives on step_1 (where the branch occurs), not step_2.
- The false branch is omitted because the SOP does not describe what happens
  for non-billing issues.
- The handoff is recorded between step_2 and step_3 where the actor changes.

---

Analyze the SOP document below and return the populated JSON object.
```
"""

_SYSTEM_CTX = LLMAdapterContext(
    actor_id="system",
    tenant_id="system",
    environment="local",
)


def _wrap(source: str, text: str) -> str:
    """Wrap document text in the exact tag the LLM adapter security gate requires."""
    header = f"[source: {source}]\n"
    return f"{_TRUST_OPEN}{header}{text}{_TRUST_CLOSE}"


def _load_extraction_schema() -> dict:
    path = _SCHEMAS_DIR / "process_extraction.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _build_system_prompt(extraction_schema: dict) -> str:
    """Insert schema JSON without interpreting other braces in the template."""
    schema_json = json.dumps(extraction_schema, indent=2)
    return _SYSTEM_PROMPT_TEMPLATE.replace("{schema_json}", schema_json)


class ProcessExtractor:
    """Extract process steps, handoffs, and decisions from normalized documents via LLM."""

    def __init__(
        self,
        adapter: LLMAdapterProtocol,
        options: JobOptions | None = None,
    ) -> None:
        self._adapter = adapter
        self._options = options or JobOptions()

    def extract(
        self,
        normalized: NormalizedInput,
        trace_id: str,
        description: str | None = None,
    ) -> ProcessExtraction:
        """Run extraction.  Always returns a ProcessExtraction; never raises."""
        active_docs = [d for d in normalized.documents if d.char_count > 0]

        if not active_docs and not normalized.documents:
            return ProcessExtraction(
                warnings=["No documents provided; skipping LLM extraction."]
            )

        if not active_docs:
            return ProcessExtraction(
                warnings=[
                    "All documents produced empty text (e.g. image-only PDFs); "
                    "skipping LLM extraction."
                ]
            )

        try:
            extraction_schema = _load_extraction_schema()
        except Exception as exc:  # noqa: BLE001
            _log.warning("Could not load process_extraction.schema.json: %s", exc)
            extraction_schema = {}

        system_prompt = _build_system_prompt(extraction_schema)

        # One combined user message with all documents wrapped individually.
        combined = "\n\n".join(
            _wrap(doc.filename, doc.text) for doc in active_docs
        )
        if description:
            combined += "\n\n" + _wrap("description", description)

        cost_limit = (
            self._options.max_cost_usd
            if self._options.max_cost_usd is not None
            else _DEFAULT_COST_LIMIT_USD
        )

        request = LLMAdapterRequest(
            request_id=str(uuid.uuid4()),
            operation=LLMAdapterOperation.complete_structured,
            input={
                "system": system_prompt,
                "messages": [{"role": "user", "content": combined}],
                "output_schema": extraction_schema,
                "max_tokens": 8192,
                "cost_limit_usd": cost_limit,
            },
            context=_SYSTEM_CTX,
            trace_id=trace_id,
        )

        response = self._adapter.handle(request)

        if response.status != LLMAdapterStatus.succeeded:
            error_info = response.result.get("error", {})
            warning = (
                f"LLM extraction failed "
                f"({error_info.get('error_code', 'unknown')}): "
                f"{error_info.get('message', str(response.result))}. "
                "Returning empty extraction."
            )
            _log.warning("Process extraction failed [%s]: %s", trace_id, warning)
            return ProcessExtraction(warnings=[warning])

        raw = response.result.get("structured_object", {})

        try:
            extraction = ProcessExtraction(
                steps=[ExtractedStep(**s) for s in raw.get("steps", [])],
                handoffs=[Handoff(**h) for h in raw.get("handoffs", [])],
                decision_points=[
                    DecisionPoint(**d) for d in raw.get("decision_points", [])
                ],
                warnings=list(raw.get("warnings", [])),
            )
        except Exception as exc:  # noqa: BLE001
            warning = f"Could not parse LLM extraction output: {exc}. Returning empty extraction."
            _log.warning("Process extraction parse error [%s]: %s", trace_id, warning)
            return ProcessExtraction(warnings=[warning])

        _log.info(
            "Process extraction complete [%s]: %d steps, %d handoffs, %d decision points",
            trace_id,
            len(extraction.steps),
            len(extraction.handoffs),
            len(extraction.decision_points),
        )
        return extraction
    
# if __name__ == "__main__":
#     import os
#     import pypdf
#     from ai_workflow_mapper.workflow.normalizer import NormalizedInput
    
#     # We pull the real Config object from your existing import path
#     from ai_workflow_mapper.platform.contracts.llm_adapter import LLMAdapterConfig

#     # 1. 🚨 SET YOUR API KEY
#     # Replace this with your actual Anthropic API key, or export it in your terminal
#     if "LLM_API_KEY" not in os.environ:
#         os.environ["LLM_API_KEY"] = "your-actual-anthropic-api-key-here"

#     # 2. Define your target local PDF file
#     pdf_filename = r"C:\Users\anany\OneDrive\Desktop\agentic innovations internship\ai_workflow_mapper\inputs\SOP Briefs.pdf" 

#     # 3. Read the text from your local PDF
#     def extract_text_from_pdf(pdf_path: str) -> str:
#         text = ""
#         try:
#             reader = pypdf.PdfReader(pdf_path)
#             for page in reader.pages:
#                 page_text = page.extract_text()
#                 if page_text:
#                     text += page_text + "\n"
#         except Exception as e:
#             print(f"❌ Error reading PDF {pdf_path}: {e}")
#         return text

#     print(f"Reading target file: {pdf_filename}...")
#     extracted_text = extract_text_from_pdf(pdf_filename)

#     if not extracted_text.strip():
#         print(f"❌ Aborting: No text could be extracted from '{pdf_filename}'.")
#         exit(1)

#     print(f"Loaded {len(extracted_text)} characters from the PDF.")

#     # 4. Wrap the text into the NormalizedInput format the Extractor expects
#     class RealDoc:
#         def __init__(self, filename: str, text: str):
#             self.filename = filename
#             self.text = '<process_content trust_level="untrusted">\n' + text
#             self.char_count = len(text)

#     document_payload = NormalizedInput(
#         documents=[RealDoc(filename=pdf_filename, text=extracted_text)]
#     )

#     # 5. Initialize your real LocalLLMAdapter
#     # We pass it the LLMAdapterConfig contract populated with basic operational settings
#     config_payload = LLMAdapterConfig(
#         environment="local",
#         implementation="local",
#         security={},  # Passing an empty dict as a fallback, or a generic string if it expects text
#         settings={
#             "model_id": "claude-sonnet-4-6",
#             "timeout_s": 90.0,
#             "cost_limit_usd": 0.5  
#         }
#     )
    
#     # Assuming LocalLLMAdapter is defined in the same project, import it here if needed
#     from ai_workflow_mapper.platform.local.llm_adapter import LocalLLMAdapter
#     real_adapter = LocalLLMAdapter(config=config_payload)

#     # 6. Kick off the execution pipeline!
#     print("\n🚀 Sending live payload to Anthropic Claude via LocalLLMAdapter...")
#     extractor = ProcessExtractor(adapter=real_adapter)
    
#     # Your print statement from earlier will now intercept and dump the REAL raw JSON here!
#     result = extractor.extract(document_payload, trace_id="live-pdf-run-101")

#     print("\n--- Execution Finished ---")
#     if result.warnings:
#         print("⚠️ Warnings Returned from pipeline:")
#         for warning in result.warnings:
#             print(f" - {warning}")