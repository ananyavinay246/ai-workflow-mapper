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