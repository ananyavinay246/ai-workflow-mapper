"""Tests for the submit_job CLI helper."""

import base64
import json
from pathlib import Path

import pytest

from ai_workflow_mapper.cli.submit_job import build_job_input, main


def test_build_job_input_encodes_file(tmp_path: Path):
    doc = tmp_path / "onboarding-sop.txt"
    doc.write_text("Step 1: receive request.", encoding="utf-8")

    job = build_job_input([doc], description="Onboarding flow")

    assert job.input.description == "Onboarding flow"
    assert len(job.input.documents) == 1
    assert job.input.documents[0].filename == "onboarding-sop.txt"
    assert job.input.documents[0].source_type == "sop"
    decoded = base64.b64decode(job.input.documents[0].content_b64).decode("utf-8")
    assert "receive request" in decoded


def test_build_job_input_rejects_unsupported_extension(tmp_path: Path):
    doc = tmp_path / "diagram.vsdx"
    doc.write_bytes(b"fake")

    with pytest.raises(ValueError, match="Unsupported file type"):
        build_job_input([doc])


def test_build_job_input_expands_directory(tmp_path: Path):
    folder = tmp_path / "sop-pack"
    folder.mkdir()
    (folder / "alpha.txt").write_text("Alpha step.", encoding="utf-8")
    (folder / "beta.md").write_text("# Beta", encoding="utf-8")
    (folder / "skip.exe").write_bytes(b"binary")

    job = build_job_input([folder])

    filenames = {doc.filename for doc in job.input.documents}
    assert filenames == {"alpha.txt", "beta.md"}


def test_build_job_input_recursive_directory(tmp_path: Path):
    root = tmp_path / "docs"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "top.txt").write_text("Top", encoding="utf-8")
    (nested / "deep.pdf").write_bytes(b"%PDF-1.4 fake")

    job = build_job_input([root], recursive=True)
    assert {doc.filename for doc in job.input.documents} == {"top.txt", "deep.pdf"}


def test_build_job_input_empty_directory(tmp_path: Path):
    folder = tmp_path / "empty"
    folder.mkdir()

    with pytest.raises(ValueError, match="No supported documents"):
        build_job_input([folder])


def test_main_local_without_llm_key(tmp_path: Path, capsys, monkeypatch):
    doc = tmp_path / "notes.md"
    doc.write_text("# Process\n\n1. Draft\n2. Review", encoding="utf-8")

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(
        "ai_workflow_mapper.platform.env_loader.load_project_env",
        lambda: False,
    )

    code = main(["--local", "--pretty", str(doc)])
    captured = capsys.readouterr()

    assert code == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "succeeded"
    assert "normalization_summary" in payload["result"]
    assert "LLM_API_KEY not set" in "\n".join(payload["result"]["normalization_summary"]["warnings"])
