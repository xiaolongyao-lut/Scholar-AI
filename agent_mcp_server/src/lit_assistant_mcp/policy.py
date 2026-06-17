"""Path access control with traversal prevention and allowlist/denylist."""

import os
from pathlib import Path
from typing import Final, NamedTuple

MAX_FILE_SIZE: Final[int] = 10 * 1024 * 1024  # 10MB


class PathDecision(NamedTuple):
    """Resolved path decision returned by PathPolicy."""

    allowed: bool
    reason: str
    path: Path | None


class PathPolicy:
    """Enforce path access policy with traversal prevention."""

    def __init__(
        self,
        repo_root: Path,
        allowed_roots: list[str],
        denied_patterns: list[str],
    ) -> None:
        """Initialize path policy.

        Args:
            repo_root: Repository root (must be absolute)
            allowed_roots: Relative paths from repo_root that are readable
            denied_patterns: Glob-style patterns to block (e.g., "**/.env*")
        """
        self.repo_root = repo_root.resolve()
        self.allowed_roots = [
            (self.repo_root / rel).resolve() for rel in allowed_roots
        ]
        self.denied_patterns = denied_patterns
        self.touched_paths: list[Path] = []

    def resolve_allowed(self, path: str | Path) -> PathDecision:
        """Resolve and check if a path is allowed.

        Returns:
            PathDecision containing allow status, reason, and canonical path.
        """
        try:
            # Normalize and resolve path (handles .., symlinks, junctions)
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = self.repo_root / candidate

            # Resolve to canonical absolute path
            resolved = candidate.resolve()

            # Also use os.path.realpath for additional symlink resolution
            realpath = Path(os.path.realpath(str(resolved)))
            real_resolved = realpath.resolve(strict=False)

            # Normalize case for Windows
            resolved_norm = Path(os.path.normcase(str(real_resolved)))
            repo_norm = Path(os.path.normcase(str(self.repo_root)))

            # Check containment using os.path.commonpath (not string prefix)
            try:
                common = Path(os.path.normcase(
                    os.path.commonpath([str(resolved_norm), str(repo_norm)])
                ))
                if common != repo_norm:
                    return PathDecision(False, "path outside repository", real_resolved)
            except ValueError:
                # Different drives on Windows
                return PathDecision(False, "path outside repository", real_resolved)

            # Check denylist (case-insensitive on Windows)
            resolved_str = str(resolved_norm)
            for pattern in self.denied_patterns:
                # Simple pattern matching: exact, suffix, or wildcard
                if pattern.startswith("**/"):
                    # Recursive pattern like "**/.env*"
                    suffix = pattern[3:]  # Remove "**/
                    if suffix.endswith("*"):
                        # Wildcard suffix like ".env*"
                        prefix = suffix[:-1]
                        for part in real_resolved.parts:
                            part_norm = os.path.normcase(part)
                            if part_norm.startswith(os.path.normcase(prefix)):
                                return PathDecision(False, f"matches denied pattern: {pattern}", real_resolved)
                    else:
                        # Exact name like ".env"
                        for part in real_resolved.parts:
                            if os.path.normcase(part) == os.path.normcase(suffix):
                                return PathDecision(False, f"matches denied pattern: {pattern}", real_resolved)
                elif pattern.endswith("/**"):
                    # Directory prefix like "workspace_artifacts/runtime_state/**"
                    prefix = pattern[:-3]
                    prefix_path = Path(os.path.normcase(str(self.repo_root / prefix)))
                    try:
                        resolved_norm.relative_to(prefix_path)
                        return PathDecision(False, f"matches denied pattern: {pattern}", real_resolved)
                    except ValueError:
                        pass
                elif "*" in pattern:
                    # Wildcard like "*credential*", "*token*", "*secret*"
                    parts = pattern.split("*")
                    if all(
                        os.path.normcase(p) in resolved_str for p in parts if p
                    ):
                        return PathDecision(False, f"matches denied pattern: {pattern}", real_resolved)

            # Check allowlist (must be under at least one allowed root)
            for allowed_root in self.allowed_roots:
                allowed_norm = Path(os.path.normcase(str(allowed_root)))
                try:
                    resolved_norm.relative_to(allowed_norm)
                    # File must exist and be readable
                    if not real_resolved.exists():
                        return PathDecision(False, "file does not exist", real_resolved)
                    if not real_resolved.is_file():
                        return PathDecision(False, "not a regular file", real_resolved)
                    # Size check
                    if real_resolved.stat().st_size > MAX_FILE_SIZE:
                        return PathDecision(False, f"file exceeds {MAX_FILE_SIZE} bytes", real_resolved)

                    # Track touched path
                    if real_resolved not in self.touched_paths:
                        self.touched_paths.append(real_resolved)

                    return PathDecision(True, "allowed", real_resolved)
                except ValueError:
                    continue

            return PathDecision(False, "not under any allowed root", real_resolved)

        except (OSError, RuntimeError) as e:
            return PathDecision(False, f"path resolution error: {e}", None)

    def is_allowed(self, path: str | Path) -> tuple[bool, str]:
        """Check if path is allowed.

        Returns:
            (allowed: bool, reason: str)
        """
        decision = self.resolve_allowed(path)
        return decision.allowed, decision.reason

    def reset_touched(self) -> list[Path]:
        """Reset and return touched paths."""
        paths = self.touched_paths.copy()
        self.touched_paths.clear()
        return paths
