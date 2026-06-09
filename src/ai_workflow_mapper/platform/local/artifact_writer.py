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
