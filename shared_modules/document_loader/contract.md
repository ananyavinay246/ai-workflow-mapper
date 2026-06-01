# Document Loader Contract

## Module Id

document_loader

## Purpose

Convert supported files into normalized text, metadata, and extracted structured elements.

## Public Operations

- detect_file_type
- load_document
- extract_text
- extract_metadata

## Inputs

File reference or bytes, filename, MIME type, caller-supplied metadata, parser options, and safety scan result.

## Outputs

Normalized document object with text, pages/sections, metadata, source spans, warnings, and parser provenance.

## Error Codes

- document_unsupported_type
- document_too_large
- document_parse_failed
- document_password_required

## Configuration

Supported file types, size limits, OCR policy, parser selection, and metadata retention rules.

## Required Behaviors

- Preserve source span references when possible
- Return warnings for partial extraction instead of silently dropping content
- Keep parser-specific objects behind the contract
- Validate file type before parsing

## Security And Privacy Rules

- Reject files that fail upload scanning
- Do not execute embedded scripts, macros, or remote references
- Redact sensitive parser diagnostics from user-facing errors

## Non-Goals

- Answering questions about document content
- Indexing documents into retrieval stores
- Rendering final reports

## Project-Local Implementation

Interns are expected to implement this module as a project-local adapter first when their project depends on it. The local implementation must keep vendor/library details behind this contract and must pass the contract tests in tests/contract_tests.md.

Recommended local paths:

- Interface or protocol: platform/contracts/document_loader
- Project-local implementation: platform/local/document_loader
- Contract tests: tests/contracts/document_loader

## Shared Replacement Criteria

- The shared implementation passes this module's contract tests.
- The project-specific acceptance gate still passes.
- Product-code call sites do not change.
- Security, privacy, logging, and audit behavior are equivalent or better.
- The technical lead approves swaps in sensitive domains.
