"""Kroki API client — render Mermaid diagrams to PNG."""

from __future__ import annotations

import os

import httpx

DEFAULT_KROKI_BASE_URL = "https://kroki.io"
DEFAULT_TIMEOUT_S = 60.0


def _resolve_timeout_s(timeout_s: float | None) -> float:
    if timeout_s is not None:
        return timeout_s
    env_val = os.environ.get("KROKI_TIMEOUT_S")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return DEFAULT_TIMEOUT_S


class KrokiError(Exception):
    """Raised when Kroki cannot render a diagram."""


class KrokiClient:
    """Convert Mermaid source to PNG via a Kroki-compatible HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("KROKI_BASE_URL") or DEFAULT_KROKI_BASE_URL).rstrip(
            "/"
        )
        self._timeout_s = _resolve_timeout_s(timeout_s)

    def mermaid_to_png(self, mermaid_source: str) -> bytes:
        """POST Mermaid source to Kroki and return PNG bytes."""
        if not mermaid_source.strip():
            raise KrokiError("Mermaid source is empty")

        url = f"{self._base_url}/mermaid/png"
        try:
            response = httpx.post(
                url,
                content=mermaid_source.encode("utf-8"),
                headers={"Content-Type": "text/plain", "Accept": "image/png"},
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as exc:
            raise KrokiError(f"Kroki request failed: {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if response.status_code != 200 or not content_type.startswith("image/png"):
            detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
            raise KrokiError(f"Kroki render failed: {detail}")

        return response.content
