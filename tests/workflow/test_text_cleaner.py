"""Unit tests for post-extraction text cleaning."""

import json

from ai_workflow_mapper.workflow.text_cleaner import clean_extracted_text


def test_whitespace_normalization():
    raw = "Step 1  \n\n\n\nStep 2  "
    result = clean_extracted_text(raw, parser="plaintext")
    assert result.text == "Step 1\n\nStep 2"
    assert not result.text.endswith(" ")


def test_ligature_repair():
    raw = "\ufb01le and \ufb02ow"
    result = clean_extracted_text(raw, parser="plaintext")
    assert result.text == "file and flow"


def test_page_footer_removal():
    pages = [
        "CONFIDENTIAL\nBody on page one\nPage 1 of 3",
        "CONFIDENTIAL\nBody on page two\nPage 2 of 3",
        "CONFIDENTIAL\nBody on page three\nPage 3 of 3",
    ]
    raw = "\f".join(pages)
    result = clean_extracted_text(raw, parser="pypdf")
    assert "Page 1 of 3" not in result.text
    assert "Page 2 of 3" not in result.text
    assert "Body on page one" in result.text
    assert "Body on page three" in result.text
    assert result.stats["footers_removed"] > 0


def test_repeating_header_removed_across_pages():
    pages = [
        "ACME SOP\nStep A",
        "ACME SOP\nStep B",
        "ACME SOP\nStep C",
    ]
    raw = "\f".join(pages)
    result = clean_extracted_text(raw, parser="pypdf")
    assert result.text.count("ACME SOP") == 0
    assert "Step A" in result.text
    assert "Step C" in result.text


def test_pipe_rows_to_markdown_table():
    raw = "Intro\nstep | owner\nSubmit | HR\nDone"
    result = clean_extracted_text(raw, parser="python-docx")
    assert "| step | owner |" in result.text
    assert "| --- | --- |" in result.text
    assert "| Submit | HR |" in result.text
    assert result.stats["tables_converted"] == 1


def test_existing_markdown_table_unchanged():
    raw = (
        "| Col 1 | Col 2 |\n"
        "| --- | --- |\n"
        "| a | b |\n"
    )
    result = clean_extracted_text(raw, parser="plaintext")
    assert result.text == raw.strip()
    assert result.stats["tables_converted"] == 0


def test_json_parser_minimal_clean():
    obj = {"steps": ["Approve", "Review"], "note": "caf\u00e9"}
    raw = json.dumps(obj, ensure_ascii=False)
    result = clean_extracted_text(raw, parser="json")
    parsed = json.loads(result.text)
    assert parsed["steps"] == ["Approve", "Review"]
    assert parsed["note"] == "café"
    assert result.stats["tables_converted"] == 0


def test_tab_separated_table():
    raw = "Name\tRole\nAlice\tManager\nBob\tAnalyst"
    result = clean_extracted_text(raw, parser="plaintext")
    assert "| Name | Role |" in result.text
    assert "| Alice | Manager |" in result.text
    assert result.stats["tables_converted"] == 1


def test_space_aligned_table():
    raw = "Name    Role\nAlice    Manager\nBob    Analyst"
    result = clean_extracted_text(raw, parser="plaintext")
    assert "| Name | Role |" in result.text
    assert "| Alice | Manager |" in result.text
    assert result.stats["tables_converted"] == 1


def test_dehyphenation():
    raw = "This is a long sen-\ntence about workflow."
    result = clean_extracted_text(raw, parser="pypdf")
    assert "sen-\ntence" not in result.text
    assert "sentence" in result.text


def test_bullet_normalization():
    raw = "• Step one\n◦ Step two"
    result = clean_extracted_text(raw, parser="plaintext")
    assert "- Step one" in result.text
    assert "- Step two" in result.text


def test_large_removal_warning():
    raw = ("HEADER\n" * 50) + "tiny"
    result = clean_extracted_text(raw, parser="plaintext")
    assert any("large portion" in w for w in result.warnings)


def test_single_pipe_row_not_converted():
    raw = "Note: use A | B syntax in prose"
    result = clean_extracted_text(raw, parser="plaintext")
    assert "| --- |" not in result.text
    assert result.stats["tables_converted"] == 0
