"""Tests for .env loading."""

import os

from ai_workflow_mapper.platform.env_loader import _read_env_text, load_project_env


def test_load_project_env_sets_llm_key_from_repo_dotenv(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_API_KEY=test-key-from-dotenv\n", encoding="utf-8")

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(
        "ai_workflow_mapper.platform.env_loader.find_project_root",
        lambda: tmp_path,
    )

    assert load_project_env() is True
    assert os.environ.get("LLM_API_KEY") == "test-key-from-dotenv"


def test_load_project_env_does_not_override_existing(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_API_KEY=from-file\n", encoding="utf-8")

    monkeypatch.setenv("LLM_API_KEY", "already-set")
    monkeypatch.setattr(
        "ai_workflow_mapper.platform.env_loader.find_project_root",
        lambda: tmp_path,
    )

    load_project_env()
    assert os.environ["LLM_API_KEY"] == "already-set"


def test_read_env_text_utf16(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_API_KEY=utf16-key\n", encoding="utf-16")

    text = _read_env_text(env_file)
    assert "LLM_API_KEY=utf16-key" in text
