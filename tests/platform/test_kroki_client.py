"""Tests for Kroki Mermaid-to-PNG client."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from ai_workflow_mapper.platform.local.kroki_client import KrokiClient, KrokiError


def test_mermaid_to_png_success():
    client = KrokiClient(base_url="https://kroki.example")
    fake_png = b"\x89PNG\r\n\x1a\nfake"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "image/png"}
    mock_response.content = fake_png
    mock_response.text = ""

    with patch("ai_workflow_mapper.platform.local.kroki_client.httpx.post", return_value=mock_response) as post:
        result = client.mermaid_to_png("flowchart TD\n  a[Start]")

    assert result == fake_png
    post.assert_called_once()
    url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs.get("url")
    assert url == "https://kroki.example/mermaid/png"
    call_kwargs = post.call_args.kwargs
    assert call_kwargs["content"] == b"flowchart TD\n  a[Start]"
    assert call_kwargs["headers"]["Content-Type"] == "text/plain"


def test_mermaid_to_png_empty_source():
    with pytest.raises(KrokiError, match="empty"):
        KrokiClient().mermaid_to_png("   ")


def test_mermaid_to_png_http_error():
    with patch(
        "ai_workflow_mapper.platform.local.kroki_client.httpx.post",
        side_effect=httpx.ConnectError("offline"),
    ):
        with pytest.raises(KrokiError, match="request failed"):
            KrokiClient().mermaid_to_png("flowchart TD\n  a[Start]")


def test_mermaid_to_png_custom_timeout(monkeypatch):
    monkeypatch.delenv("KROKI_TIMEOUT_S", raising=False)
    client = KrokiClient(base_url="https://kroki.example", timeout_s=180.0)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "image/png"}
    mock_response.content = b"\x89PNG"
    mock_response.text = ""

    with patch("ai_workflow_mapper.platform.local.kroki_client.httpx.post", return_value=mock_response) as post:
        client.mermaid_to_png("flowchart TD\n  a[Start]")

    assert post.call_args.kwargs["timeout"] == 180.0


def test_mermaid_to_png_timeout_from_env(monkeypatch):
    monkeypatch.setenv("KROKI_TIMEOUT_S", "90")
    client = KrokiClient(base_url="https://kroki.example")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "image/png"}
    mock_response.content = b"\x89PNG"
    mock_response.text = ""

    with patch("ai_workflow_mapper.platform.local.kroki_client.httpx.post", return_value=mock_response) as post:
        client.mermaid_to_png("flowchart TD\n  a[Start]")

    assert post.call_args.kwargs["timeout"] == 90.0


def test_mermaid_to_png_bad_response():
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.headers = {"content-type": "text/plain"}
    mock_response.text = "Syntax error in graph"
    mock_response.content = b""

    with patch("ai_workflow_mapper.platform.local.kroki_client.httpx.post", return_value=mock_response):
        with pytest.raises(KrokiError, match="render failed"):
            KrokiClient().mermaid_to_png("flowchart TD\n  broken")
