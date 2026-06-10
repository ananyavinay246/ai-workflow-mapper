"""Local filesystem writer for job artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path


class ArtifactWriter:
    """Write artifact files under a job-scoped relative directory."""

    def __init__(self, base_dir: str | Path = "artifacts") -> None:
        self._base_dir = Path(base_dir)

    def write_text(self, job_id: str, filename: str, content: str) -> tuple[str, str]:
        """Write content and return (relative_path, sha256 checksum)."""
        job_dir = self._base_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / filename
        path.write_text(content, encoding="utf-8")
        rel_path = str(Path("artifacts") / job_id / filename).replace("\\", "/")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return rel_path, f"sha256:{digest}"

    def write_bytes(self, job_id: str, filename: str, data: bytes) -> tuple[str, str]:
        """Write binary content and return (relative_path, sha256 checksum)."""
        job_dir = self._base_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / filename
        path.write_bytes(data)
        rel_path = str(Path("artifacts") / job_id / filename).replace("\\", "/")
        digest = hashlib.sha256(data).hexdigest()
        return rel_path, f"sha256:{digest}"

    def save_mermaid_png(
        self,
        job_id: str,
        filename: str,
        mermaid_source: str,
        *,
        kroki: "KrokiClient | None" = None,
    ) -> tuple[str, str]:
        """Render Mermaid via Kroki and save PNG. Returns (relative_path, checksum)."""
        from ai_workflow_mapper.platform.local.kroki_client import KrokiClient

        client = kroki or KrokiClient()
        png_bytes = client.mermaid_to_png(mermaid_source)
        return self.write_bytes(job_id, filename, png_bytes)
