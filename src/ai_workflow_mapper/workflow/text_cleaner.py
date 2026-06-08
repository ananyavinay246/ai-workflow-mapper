"""Post-extraction text cleaning for normalized documents."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Unicode characters to remove outright
_REMOVE_CHARS = {
    "\ufeff",  # BOM
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\u2060",  # word joiner
    "\u00ad",  # soft hyphen
    "\x00",  # NUL
}

# Private-use / PDF ligature replacements
_LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
}

# Common mojibake sequences (UTF-8 misread as Latin-1)
_MOJIBAKE_MAP = {
    "\u00e2\u0080\u0099": "'",
    "\u00e2\u0080\u0098": "'",
    "\u00e2\u0080\u009c": '"',
    "\u00e2\u0080\u009d": '"',
    "\u00e2\u0080\u0094": "\u2014",
    "\u00e2\u0080\u0093": "\u2013",
    "\u00c3\u00a9": "\u00e9",
    "\u00c3\u00a0": "\u00e0",
}

_PAGE_PATTERNS = [
    re.compile(r"^\s*page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*page\s+\d+\s*/\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*page\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*-\s*\d+\s*-\s*$"),
]

_BULLET_PATTERN = re.compile(r"^(\s*)[•◦▪●]\s+")
_HYPHEN_BREAK_PATTERN = re.compile(r"(\w)-\n(\w)")
_MARKDOWN_TABLE_ROW = re.compile(r"^\|.+\|$")
_MARKDOWN_TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|$")

_LARGE_REMOVAL_THRESHOLD = 0.40


@dataclass
class CleanResult:
    text: str
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def clean_extracted_text(
    text: str,
    *,
    parser: str = "unknown",
    filename: str = "",
) -> CleanResult:
    """Run the full post-extraction cleaning pipeline."""
    raw_len = len(text)
    stats: dict[str, Any] = {
        "chars_before": raw_len,
        "filename": filename,
        "parser": parser,
        "pages_processed": 0,
        "footers_removed": 0,
        "tables_converted": 0,
    }
    warnings: list[str] = []

    cleaned = _repair_unicode(text)

    if parser == "json":
        cleaned = cleaned.strip()
        stats["chars_after"] = len(cleaned)
        _maybe_warn_large_removal(raw_len, len(cleaned), warnings)
        return CleanResult(text=cleaned, warnings=warnings, stats=stats)

    cleaned, page_stats = _remove_headers_footers(cleaned)
    stats["pages_processed"] = page_stats["pages"]
    stats["footers_removed"] = page_stats["lines_removed"]

    cleaned = _dehyphenate_line_breaks(cleaned)
    cleaned = _normalize_bullets(cleaned)
    cleaned = _collapse_duplicate_lines(cleaned)

    cleaned, tables_converted = _convert_tables_to_markdown(cleaned)
    stats["tables_converted"] = tables_converted

    cleaned = _normalize_whitespace(cleaned)
    stats["chars_after"] = len(cleaned)
    _maybe_warn_large_removal(raw_len, len(cleaned), warnings)

    return CleanResult(text=cleaned, warnings=warnings, stats=stats)


def _repair_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for char in _REMOVE_CHARS:
        text = text.replace(char, "")
    for old, new in _LIGATURE_MAP.items():
        text = text.replace(old, new)
    for old, new in _MOJIBAKE_MAP.items():
        text = text.replace(old, new)
    return text


def _remove_headers_footers(text: str) -> tuple[str, dict[str, int]]:
    pages = text.split("\f")
    page_count = len(pages)
    stats = {"pages": page_count, "lines_removed": 0}

    if page_count <= 1 and "\f" not in text:
        lines = text.splitlines()
        filtered = [ln for ln in lines if not _is_page_marker_line(ln)]
        stats["lines_removed"] = len(lines) - len(filtered)
        return "\n".join(filtered), stats

    cleaned_pages: list[str] = []
    line_frequency: dict[str, int] = {}

    for page in pages:
        page_lines = page.splitlines()
        for line in page_lines:
            normalized = line.strip()
            if normalized and not _is_page_marker_line(line):
                line_frequency[normalized] = line_frequency.get(normalized, 0) + 1

    repeat_threshold = max(2, int(page_count * 0.5))
    repeating = {ln for ln, count in line_frequency.items() if count >= repeat_threshold}

    for page in pages:
        kept: list[str] = []
        for line in page.splitlines():
            stripped = line.strip()
            if _is_page_marker_line(line):
                stats["lines_removed"] += 1
                continue
            if stripped in repeating:
                stats["lines_removed"] += 1
                continue
            kept.append(line)
        cleaned_pages.append("\n".join(kept))

    return "\n\n".join(cleaned_pages), stats


def _is_page_marker_line(line: str) -> bool:
    return any(p.match(line) for p in _PAGE_PATTERNS)


def _dehyphenate_line_breaks(text: str) -> str:
    return _HYPHEN_BREAK_PATTERN.sub(r"\1\2", text)


def _normalize_bullets(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(_BULLET_PATTERN.sub(r"\1- ", line))
    return "\n".join(lines)


def _collapse_duplicate_lines(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    result = [lines[0]]
    for line in lines[1:]:
        if line.strip() and line.strip() == result[-1].strip():
            continue
        result.append(line)
    return "\n".join(result)


def _normalize_whitespace(text: str) -> str:
    lines = [ln.rstrip(" \t") for ln in text.splitlines()]
    out: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run <= 1:
                out.append("")
            continue
        blank_run = 0
        out.append(line)
    return "\n".join(out).strip()


def _convert_tables_to_markdown(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    result: list[str] = []
    i = 0
    tables_converted = 0

    while i < len(lines):
        if _is_markdown_table_block(lines, i):
            block, consumed = _consume_markdown_table(lines, i)
            result.extend(block)
            i += consumed
            continue

        pipe_block, consumed = _try_consume_pipe_rows(lines, i)
        if pipe_block is not None:
            result.extend(pipe_block)
            tables_converted += 1
            i += consumed
            continue

        tab_block, consumed = _try_consume_tab_rows(lines, i)
        if tab_block is not None:
            result.extend(tab_block)
            tables_converted += 1
            i += consumed
            continue

        space_block, consumed = _try_consume_space_aligned_rows(lines, i)
        if space_block is not None:
            result.extend(space_block)
            tables_converted += 1
            i += consumed
            continue

        result.append(lines[i])
        i += 1

    return "\n".join(result), tables_converted


def _is_markdown_table_block(lines: list[str], start: int) -> bool:
    if start >= len(lines) or not _MARKDOWN_TABLE_ROW.match(lines[start].strip()):
        return False
    if start + 1 >= len(lines):
        return False
    return bool(_MARKDOWN_TABLE_SEP.match(lines[start + 1].strip()))


def _consume_markdown_table(lines: list[str], start: int) -> tuple[list[str], int]:
    block: list[str] = []
    i = start
    while i < len(lines) and _MARKDOWN_TABLE_ROW.match(lines[i].strip()):
        block.append(lines[i])
        i += 1
    return block, i - start


def _try_consume_pipe_rows(lines: list[str], start: int) -> tuple[list[str] | None, int]:
    block: list[list[str]] = []
    i = start
    col_count: int | None = None

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            break
        if _MARKDOWN_TABLE_ROW.match(line.strip()):
            break
        if "|" not in line:
            break
        cells = [_clean_cell(c) for c in line.split("|")]
        if len(cells) < 2:
            break
        if col_count is None:
            col_count = len(cells)
        elif len(cells) != col_count:
            break
        block.append(cells)
        i += 1

    if len(block) < 2:
        return None, 0
    return _render_markdown_table(block), i - start


def _try_consume_tab_rows(lines: list[str], start: int) -> tuple[list[str] | None, int]:
    block: list[list[str]] = []
    i = start
    col_count: int | None = None

    while i < len(lines):
        line = lines[i]
        if not line.strip() or "\t" not in line:
            break
        cells = [_clean_cell(c) for c in line.split("\t")]
        if len(cells) < 2:
            break
        if col_count is None:
            col_count = len(cells)
        elif len(cells) != col_count:
            break
        block.append(cells)
        i += 1

    if len(block) < 2:
        return None, 0
    return _render_markdown_table(block), i - start


def _try_consume_space_aligned_rows(
    lines: list[str], start: int
) -> tuple[list[str] | None, int]:
    block: list[list[str]] = []
    i = start
    col_count: int | None = None

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            break
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 2:
            break
        cells = [_clean_cell(c) for c in parts]
        if col_count is None:
            col_count = len(cells)
        elif len(cells) != col_count:
            break
        block.append(cells)
        i += 1

    if len(block) < 2:
        return None, 0
    return _render_markdown_table(block), i - start


def _clean_cell(value: str) -> str:
    return value.strip().replace("|", "\\|")


def _render_markdown_table(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    header = rows[0]
    width = len(header)
    sep = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in rows[1:]:
        padded = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(padded[:width]) + " |")
    return lines


def _maybe_warn_large_removal(before: int, after: int, warnings: list[str]) -> None:
    if before == 0:
        return
    removed_ratio = (before - after) / before
    if removed_ratio > _LARGE_REMOVAL_THRESHOLD:
        warnings.append(
            "Text cleaning removed a large portion of extracted content; review source document"
        )
