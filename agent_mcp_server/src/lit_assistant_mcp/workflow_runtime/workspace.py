"""Artifact workspace constrained to the agent MCP workflow root."""

import json
from pathlib import Path
from typing import Any

from ..redaction import SecretRedactor

MAX_ARTIFACT_BYTES: int = 512 * 1024
MAX_READ_CHARS: int = 120_000
MAX_BINARY_ARTIFACT_BYTES: int = 8 * 1024 * 1024


class ArtifactWorkspace:
    """Read and write redacted workflow artifacts under one local root."""

    def __init__(self, repo_root: Path, artifact_root: Path | None = None) -> None:
        """Create an artifact workspace.

        Args:
            repo_root: Absolute repository root used to derive the default artifact root.
            artifact_root: Optional absolute or repo-relative artifact root.

        Raises:
            ValueError: If paths are not valid repository-contained paths.
        """
        if not repo_root.is_absolute():
            raise ValueError("repo_root must be absolute")
        self.repo_root = repo_root.resolve()
        root = artifact_root or self.repo_root / "workspace_artifacts" / "agent_mcp_workflows"
        if not root.is_absolute():
            root = self.repo_root / root
        self.artifact_root = root.resolve()
        self._ensure_under_repo(self.artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def write_text(self, path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
        """Write a redacted UTF-8 text artifact.

        Args:
            path: Relative artifact path. Absolute paths and traversal are rejected.
            content: Text content to write after redaction.
            overwrite: Whether an existing file may be replaced.

        Returns:
            Artifact metadata.
        """
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        redacted = SecretRedactor.scan(content)
        data = redacted.encode("utf-8")
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
        target = self.resolve_artifact(path, must_exist=False)
        if target.exists() and not overwrite:
            raise FileExistsError(f"artifact already exists: {self.relative(target)}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {
            "path": self.relative(target),
            "bytes": len(data),
            "redacted": redacted != content,
        }

    def write_json(self, path: str, payload: dict[str, Any], overwrite: bool = False) -> dict[str, Any]:
        """Write a JSON artifact after serialization and redaction."""
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        if not path.lower().endswith(".json"):
            raise ValueError("JSON workflow artifacts must use .json extension")
        return self.write_text(path, serialized, overwrite=overwrite)

    def write_bytes(self, path: str, content: bytes, overwrite: bool = False) -> dict[str, Any]:
        """Write a bounded binary artifact under the workflow workspace.

        Args:
            path: Relative artifact path. Absolute paths and traversal are rejected.
            content: Raw bytes. Binary artifacts are never returned inline.
            overwrite: Whether an existing file may be replaced.
        """
        if not isinstance(content, bytes):
            raise ValueError("content must be bytes")
        if len(content) > MAX_BINARY_ARTIFACT_BYTES:
            raise ValueError(f"binary artifact exceeds {MAX_BINARY_ARTIFACT_BYTES} bytes")
        target = self.resolve_artifact(path, must_exist=False)
        if target.exists() and not overwrite:
            raise FileExistsError(f"artifact already exists: {self.relative(target)}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {
            "path": self.relative(target),
            "bytes": len(content),
            "redacted": False,
        }

    def read_text(self, path: str, max_chars: int = MAX_READ_CHARS) -> dict[str, Any]:
        """Read a redacted text artifact."""
        if not isinstance(max_chars, int) or max_chars < 1 or max_chars > MAX_READ_CHARS:
            raise ValueError(f"max_chars must be between 1 and {MAX_READ_CHARS}")
        target = self.resolve_artifact(path, must_exist=True)
        content = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > max_chars
        content = SecretRedactor.scan(content[:max_chars])
        return {
            "path": self.relative(target),
            "content": content,
            "truncated": truncated,
        }

    def read_json(self, path: str) -> dict[str, Any]:
        """Read a JSON artifact as an object."""
        target = self.resolve_artifact(path, must_exist=True)
        if target.suffix.lower() != ".json":
            raise ValueError("workflow artifact must be a .json file")
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("workflow JSON must contain an object")
        return payload

    def list_artifacts(self, max_entries: int = 200) -> list[dict[str, Any]]:
        """List non-audit artifacts under the workspace root."""
        if not isinstance(max_entries, int) or max_entries < 1 or max_entries > 1000:
            raise ValueError("max_entries must be between 1 and 1000")
        entries: list[dict[str, Any]] = []
        for path in sorted(self.artifact_root.rglob("*"), key=lambda item: str(item).lower()):
            if len(entries) >= max_entries:
                break
            if not path.is_file() or ".audit" in path.relative_to(self.artifact_root).parts:
                continue
            entries.append(
                {
                    "path": self.relative(path),
                    "bytes": path.stat().st_size,
                    "modified_at": path.stat().st_mtime,
                }
            )
        return entries

    def resolve_artifact(self, path: str, must_exist: bool) -> Path:
        """Resolve a relative artifact path and enforce workspace containment."""
        if not isinstance(path, str) or not path.strip():
            raise ValueError("artifact path must be a non-empty string")
        raw = Path(path)
        if raw.is_absolute():
            raise ValueError("artifact path must be relative")
        if any(part in {"", ".", ".."} for part in raw.parts):
            raise ValueError("artifact path must not contain traversal segments")
        if ".audit" in raw.parts:
            raise ValueError("audit artifacts are not readable through artifact tools")
        target = (self.artifact_root / raw).resolve()
        self._ensure_under_artifact_root(target)
        if must_exist and (not target.exists() or not target.is_file()):
            raise FileNotFoundError(f"artifact does not exist: {path}")
        return target

    def relative(self, path: Path) -> str:
        """Return an artifact-root-relative path."""
        return path.resolve().relative_to(self.artifact_root).as_posix()

    def _ensure_under_repo(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError("artifact root must stay inside the repository") from exc

    def _ensure_under_artifact_root(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.artifact_root)
        except ValueError as exc:
            raise ValueError("artifact path escapes workflow workspace") from exc
