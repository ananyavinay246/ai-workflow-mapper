# AI Workflow Mapper Changelog

## 0.1.0 - Specification Scaffold

- Added production source-of-truth artifact structure.
- Added starter contracts, acceptance gate, evaluation, operations, and example artifact locations.

## 0.1.1 - Shared Modules
6/1/2026:

- Added `AGENTS.md` and templated `pyproject.toml` from the README.

6/2/2026:

- Implemented all the `shared_modules/` features: `document_loader`, `evaluation_harness`, `llm_adapter`, `report_renderer`. Ensured that all of the code validates `schemas/`, and check `acceptance.md`.

6/3/2026:

- Implemented the API under `src/ai_workflow_mapper/api` according to the spec. 
- Implemented the Input Normalizer in file `normalizer.py`. The file pushes documents with .txt, .md, .docx, .json, and .pdf to `platform/local/document_loader.py`.

6/4/2026:

- Added domain JSON schemas (`workflow_input`, `job_options`, `workflow_result`, `process_extraction`, `process_graph`, `analysis_findings`, `citation`, `diagram_artifact`) and wired `$ref` into `input.schema.json` / `output.schema.json`.
- Narrowed Pydantic API models; processor returns `workflow_result` with `normalization_summary`.
- Implemented Process Extractor (`workflow/extractor.py`): normalizes → LLM structured extraction → `ProcessExtraction`.

6/5/2026:

- Implemented Process Graph Builder (`workflow/graph_builder.py`): `ProcessExtraction` → canonical `ProcessGraph` with nodes, edges, actors, swimlanes.

6/7/2026:

- Improved the LLM prompt and created a `text_cleaner.py` that removes unnecessary characters and details from the text.

6/8/2026:

- Implemented Mermaid Diagram Generator (`workflow/diagram_generator.py`, `workflow/mermaid_renderer.py`): opt-in via `diagram_formats: ["mermaid"]`, produces flowchart and swimlane artifacts on `JobOutput.artifacts[]`.

6/9/2026:

- Added Kroki PNG export (`platform/local/kroki_client.py`): opt-in via `diagram_formats: ["png"]` or CLI `--png`.
- Implemented Bottleneck Analyzer (`workflow/bottleneck_heuristics.py`, `workflow/evidence_matcher.py`, `workflow/bottleneck_analyzer.py`): deterministic graph heuristics after ProcessGraph build; document quote evidence; optional LLM narrative enrichment in `thorough` mode. Populates `result.analysis.bottlenecks` and top-level `JobOutput.citations`.

6/10/2026:

- Modified LLM prompt to consolidate steps in workflow, and improved heuristics to detect bottlenecks better.
- Implemented Redundancy Detector (`workflow/label_similarity.py`, `workflow/redundancy_heuristics.py`, `workflow/redundancy_analyzer.py`): four spec-aligned redundancy signals after ProcessGraph build; document quote evidence; optional LLM enrichment in `thorough` mode. Populates `result.analysis.redundancies` and extends `JobOutput.citations`.

6/11/2026:

- Implemented Automation Opportunity Scorer (`workflow/automation_heuristics.py`, `workflow/automation_analyzer.py`): five spec-aligned automation signals with ROI ranking after ProcessGraph build; document quote evidence; optional LLM enrichment in `thorough` mode. Populates `result.analysis.automation_opportunities` and extends `JobOutput.citations`.
- Fixed `thorough`-mode enrichment schema validation: include `$defs/evidence` in narrow output schemas so `#/$defs/evidence` resolves without a RefResolver.

6/12/2026:

- Implemented Analysis Report Generator (`workflow/report_data_builder.py`, `workflow/report_generator.py`): assembles all seven report sections, renders via `LocalReportRenderer` (Markdown/DOCX/PDF), attaches `type=report` artifacts. Activated by `JobOptions.output_format` or CLI `--report` / `--report-format`.