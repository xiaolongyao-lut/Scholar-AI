"""Source inspection tools with path policy, redaction, and audit support."""

import ast
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..audit import AuditLog
from ..policy import PathPolicy
from ..redaction import SecretRedactor
from ..result import safe_result

DEFAULT_ALLOWED_ROOTS: list[str] = [
    "literature_assistant/",
    "agent_mcp_server/",
    "frontend/src/",
    "tests/",
    "docs/architecture/",
    "docs/plans/2026-06-17-literature-assistant-agent-mcp-toolbox-plan.md",
    "README.md",
    "pyproject.toml",
    "AI_WORKSPACE_GUIDE.md",
]

DEFAULT_DENIED_PATTERNS: list[str] = [
    "**/.env*",
    "workspace_artifacts/runtime_state/**",
    "workspace_artifacts/backups/**",
    "workspace_artifacts/generated/**",
    "workspace_artifacts/agent_mcp_workflows/.audit/**",
    ".rollback_snapshots/**",
    ".git/**",
    ".venv-*/**",
    ".claude/**",
    ".codex/**",
    "github/**",
    "logs/**",
    "*credential*",
    "*token*",
    "*secret*",
    "*password*",
]

TEXT_EXTENSIONS: set[str] = {
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

MAX_SEARCH_RESULTS: int = 200
MAX_READ_CHARS: int = 80_000
MAX_REFERENCE_RESULTS: int = 200
MAX_ENTRYPOINT_FILES: int = 30


@dataclass(frozen=True)
class SourceSymbol:
    """Public source symbol shape returned by source.read_symbols."""

    name: str
    kind: str
    line: int
    end_line: int | None


class SourceTools:
    """Safe source inspection operations for host agents."""

    def __init__(
        self,
        repo_root: Path,
        policy: PathPolicy,
        audit: AuditLog | None = None,
    ) -> None:
        """Create source tools bound to a repository.

        Args:
            repo_root: Absolute repository root.
            policy: Path policy used for every read/search target.
            audit: Optional audit writer. Tools still return safely when omitted.
        """
        if not repo_root.is_absolute():
            raise ValueError("repo_root must be absolute")
        self.repo_root = repo_root.resolve()
        self.policy = policy
        self.audit = audit

    def list_tree(
        self,
        root: str = ".",
        max_depth: int = 3,
        max_entries: int = 500,
    ) -> dict[str, Any]:
        """List allowed source files below a root.

        Args:
            root: Relative root to list.
            max_depth: Maximum directory depth from root, inclusive.
            max_entries: Maximum returned entries.

        Returns:
            Safe result containing file and directory entries.
        """
        started = time.perf_counter()
        self._validate_positive_int(max_depth, "max_depth", upper=10)
        self._validate_positive_int(max_entries, "max_entries", upper=5000)
        args = {"root": root, "max_depth": max_depth, "max_entries": max_entries}
        decision = self.policy.resolve_allowed(root)
        base_path = decision.path
        if not decision.allowed:
            # Directory roots are common for listing; evaluate containment even
            # though PathPolicy only allows files for direct reads.
            base_path = self._resolve_directory_root(root)
            if base_path is None:
                return self._finish(
                    "source.list_tree",
                    args,
                    safe_result([], error=True, error_code="path_blocked", message=decision.reason),
                    started,
                    decision.reason,
                )
        assert base_path is not None

        entries: list[dict[str, Any]] = []
        for path in self._iter_files_and_dirs(base_path, max_depth):
            if len(entries) >= max_entries:
                break
            rel_path = self._relative(path)
            if path.is_dir():
                entries.append({"path": rel_path, "type": "directory"})
                continue
            allowed, reason = self.policy.is_allowed(path)
            if allowed:
                entries.append(
                    {
                        "path": rel_path,
                        "type": "file",
                        "size": path.stat().st_size,
                    }
                )
            elif "denied pattern" not in reason.lower():
                continue

        result = safe_result(
            {
                "root": self._relative(base_path),
                "entries": entries,
                "truncated": len(entries) >= max_entries,
            }
        )
        return self._finish("source.list_tree", args, result, started, "allowed")

    def search(
        self,
        query: str,
        root: str = ".",
        max_results: int = 50,
        case_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Search text files under allowed roots.

        Args:
            query: Literal text query. Regex is intentionally unsupported.
            root: Relative root to search.
            max_results: Maximum matches to return.
            case_sensitive: Whether matching is case-sensitive.

        Returns:
            Safe result containing matching file paths, line numbers, and text.
        """
        started = time.perf_counter()
        if not isinstance(query, str) or not query:
            raise ValueError("query must be a non-empty string")
        self._validate_positive_int(max_results, "max_results", upper=MAX_SEARCH_RESULTS)
        args = {
            "query": query[:200],
            "root": root,
            "max_results": max_results,
            "case_sensitive": case_sensitive,
        }
        root_path = self._resolve_directory_root(root)
        if root_path is None:
            return self._finish(
                "source.search",
                args,
                safe_result([], error=True, error_code="path_blocked", message="root is not an allowed directory"),
                started,
                "root blocked",
            )

        needle = query if case_sensitive else query.lower()
        matches: list[dict[str, Any]] = []
        for path in self._iter_text_files(root_path):
            allowed, _ = self.policy.is_allowed(path)
            if not allowed:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matches.append(
                        {
                            "path": self._relative(path),
                            "line": line_no,
                            "text": SecretRedactor.scan(line.strip()),
                        }
                    )
                    if len(matches) >= max_results:
                        result = safe_result({"query": query, "matches": matches, "truncated": True})
                        return self._finish("source.search", args, result, started, "allowed")

        result = safe_result({"query": query, "matches": matches, "truncated": False})
        return self._finish("source.search", args, result, started, "allowed")

    def read_file(self, path: str, max_chars: int = MAX_READ_CHARS) -> dict[str, Any]:
        """Read a safe source text file.

        Args:
            path: Relative or absolute file path.
            max_chars: Maximum characters to return.

        Returns:
            Safe result containing redacted text content.
        """
        started = time.perf_counter()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        self._validate_positive_int(max_chars, "max_chars", upper=MAX_READ_CHARS)
        args = {"path": path, "max_chars": max_chars}
        decision = self.policy.resolve_allowed(path)
        if not decision.allowed or decision.path is None:
            return self._finish(
                "source.read_file",
                args,
                safe_result(None, error=True, error_code="path_blocked", message=decision.reason),
                started,
                decision.reason,
            )
        if not self._is_text_file(decision.path):
            return self._finish(
                "source.read_file",
                args,
                safe_result(None, error=True, error_code="not_text_file", message="file type is not allowed"),
                started,
                "not text file",
            )

        content = decision.path.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > max_chars
        content = content[:max_chars]
        result = safe_result(
            {
                "path": self._relative(decision.path),
                "content": content,
                "truncated": truncated,
            }
        )
        return self._finish("source.read_file", args, result, started, "allowed")

    def read_symbols(self, path: str) -> dict[str, Any]:
        """Read top-level Python symbols from a safe source file.

        Args:
            path: Relative or absolute Python source path.

        Returns:
            Safe result containing function, class, and async function symbols.
        """
        started = time.perf_counter()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        args = {"path": path}
        decision = self.policy.resolve_allowed(path)
        if not decision.allowed or decision.path is None:
            return self._finish(
                "source.read_symbols",
                args,
                safe_result(None, error=True, error_code="path_blocked", message=decision.reason),
                started,
                decision.reason,
            )
        if decision.path.suffix.lower() != ".py":
            return self._finish(
                "source.read_symbols",
                args,
                safe_result(None, error=True, error_code="unsupported_file_type", message="only Python files are supported"),
                started,
                "unsupported file type",
            )

        try:
            tree = ast.parse(decision.path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            return self._finish(
                "source.read_symbols",
                args,
                safe_result(
                    None,
                    error=True,
                    error_code="parse_error",
                    message=f"Python syntax error at line {exc.lineno}",
                ),
                started,
                "parse error",
            )

        symbols = [self._symbol_from_node(node) for node in tree.body]
        result = safe_result(
            {
                "path": self._relative(decision.path),
                "symbols": [
                    {
                        "name": symbol.name,
                        "kind": symbol.kind,
                        "line": symbol.line,
                        "end_line": symbol.end_line,
                    }
                    for symbol in symbols
                    if symbol is not None
                ],
            }
        )
        return self._finish("source.read_symbols", args, result, started, "allowed")

    def inspect_routes(self, root: str = "literature_assistant/core", max_routes: int = 200) -> dict[str, Any]:
        """Inspect FastAPI-style route decorators without importing modules.

        Args:
            root: Safe source directory to inspect.
            max_routes: Maximum route records to return.

        Returns:
            Safe result containing static route decorator records.
        """
        started = time.perf_counter()
        self._validate_positive_int(max_routes, "max_routes", upper=1000)
        args = {"root": root, "max_routes": max_routes}
        root_path = self._resolve_directory_root(root)
        if root_path is None:
            return self._finish(
                "source.inspect_routes",
                args,
                safe_result([], error=True, error_code="path_blocked", message="root is not an allowed directory"),
                started,
                "root blocked",
            )
        routes: list[dict[str, Any]] = []
        for path in self._iter_python_files(root_path):
            if len(routes) >= max_routes:
                break
            routes.extend(self._extract_routes(path, max_routes - len(routes)))
        result = safe_result({"root": self._relative(root_path), "routes": routes, "truncated": len(routes) >= max_routes})
        return self._finish("source.inspect_routes", args, result, started, "allowed")

    def find_references(
        self,
        symbol: str,
        root: str = ".",
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Find bounded static references to an identifier or text symbol.

        Args:
            symbol: Identifier or literal text to find.
            root: Safe source directory to search.
            max_results: Maximum reference records.

        Returns:
            Safe result containing file paths and line snippets.
        """
        started = time.perf_counter()
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        self._validate_positive_int(max_results, "max_results", upper=MAX_REFERENCE_RESULTS)
        args = {"symbol": symbol[:200], "root": root, "max_results": max_results}
        root_path = self._resolve_directory_root(root)
        if root_path is None:
            return self._finish(
                "source.find_references",
                args,
                safe_result([], error=True, error_code="path_blocked", message="root is not an allowed directory"),
                started,
                "root blocked",
            )
        matches = self._find_reference_matches(symbol=symbol, root_path=root_path, max_results=max_results)
        result = safe_result({"symbol": symbol, "references": matches, "truncated": len(matches) >= max_results})
        return self._finish("source.find_references", args, result, started, "allowed")

    def explain_entrypoints(
        self,
        path: str,
        max_depth: int = 2,
        max_files: int = MAX_ENTRYPOINT_FILES,
    ) -> dict[str, Any]:
        """Sketch imports reachable from a Python entrypoint without importing code.

        Args:
            path: Python source file to inspect.
            max_depth: Maximum import-follow depth.
            max_files: Maximum files in the dependency sketch.

        Returns:
            Safe result containing a bounded dependency sketch.
        """
        started = time.perf_counter()
        self._validate_positive_int(max_depth, "max_depth", upper=5)
        self._validate_positive_int(max_files, "max_files", upper=100)
        args = {"path": path, "max_depth": max_depth, "max_files": max_files}
        decision = self.policy.resolve_allowed(path)
        if not decision.allowed or decision.path is None:
            return self._finish(
                "source.explain_entrypoints",
                args,
                safe_result(None, error=True, error_code="path_blocked", message=decision.reason),
                started,
                decision.reason,
            )
        if decision.path.suffix.lower() != ".py":
            return self._finish(
                "source.explain_entrypoints",
                args,
                safe_result(None, error=True, error_code="unsupported_file_type", message="only Python files are supported"),
                started,
                "unsupported file type",
            )
        graph = self._build_entrypoint_graph(decision.path, max_depth=max_depth, max_files=max_files)
        result = safe_result({"entrypoint": self._relative(decision.path), "files": graph})
        return self._finish("source.explain_entrypoints", args, result, started, "allowed")

    def _finish(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        started: float,
        reason: str,
    ) -> dict[str, Any]:
        if self.audit is not None:
            touched = self.policy.reset_touched()
            self.audit.log(
                tool_name=tool_name,
                args_summary=args,
                touched_paths=touched,
                allow_block_reason=reason,
                result_preview=str(result.get("data")),
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code=result.get("error_code"),
            )
        return result

    def _resolve_directory_root(self, root: str) -> Path | None:
        candidate = Path(root)
        if not candidate.is_absolute():
            candidate = self.repo_root / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        if not resolved.exists() or not resolved.is_dir():
            return None
        for child in resolved.rglob("*"):
            if child.is_file():
                allowed, _ = self.policy.is_allowed(child)
                self.policy.reset_touched()
                if allowed:
                    return resolved
        return None

    def _iter_files_and_dirs(self, root: Path, max_depth: int) -> Iterable[Path]:
        for path in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
            rel = path.relative_to(root)
            depth = len(rel.parts)
            if depth <= max_depth:
                yield path

    def _iter_text_files(self, root: Path) -> Iterable[Path]:
        for path in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
            if path.is_file() and self._is_text_file(path):
                yield path

    def _iter_python_files(self, root: Path) -> Iterable[Path]:
        for path in sorted(root.rglob("*.py"), key=lambda p: str(p).lower()):
            if path.is_file() and self.policy.is_allowed(path)[0]:
                yield path

    def _extract_routes(self, path: Path, remaining: int) -> list[dict[str, Any]]:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            return []
        routes: list[dict[str, Any]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                route = self._route_from_decorator(path, node, decorator)
                if route is not None:
                    routes.append(route)
                    if len(routes) >= remaining:
                        return routes
        return routes

    def _route_from_decorator(
        self,
        path: Path,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        decorator: ast.expr,
    ) -> dict[str, Any] | None:
        call = decorator if isinstance(decorator, ast.Call) else None
        if call is None:
            return None
        method = self._route_method(call.func)
        if method is None:
            return None
        route_path = ""
        if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            route_path = call.args[0].value
        name = None
        for keyword in call.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                name = keyword.value.value
        return {
            "file": self._relative(path),
            "function": node.name,
            "method": method.upper(),
            "path": route_path,
            "name": name,
            "line": node.lineno,
        }

    def _route_method(self, func: ast.expr) -> str | None:
        route_methods = {"get", "post", "put", "patch", "delete", "options", "head", "api_route"}
        if isinstance(func, ast.Attribute) and func.attr in route_methods:
            return "route" if func.attr == "api_route" else func.attr
        return None

    def _find_reference_matches(self, symbol: str, root_path: Path, max_results: int) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        needle = symbol.strip()
        for path in self._iter_text_files(root_path):
            allowed, _ = self.policy.is_allowed(path)
            if not allowed:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, start=1):
                if needle in line:
                    matches.append(
                        {
                            "path": self._relative(path),
                            "line": line_no,
                            "text": SecretRedactor.scan(line.strip()),
                        }
                    )
                    if len(matches) >= max_results:
                        return matches
        return matches

    def _build_entrypoint_graph(self, path: Path, max_depth: int, max_files: int) -> list[dict[str, Any]]:
        visited: set[Path] = set()
        queue: list[tuple[Path, int]] = [(path.resolve(), 0)]
        graph: list[dict[str, Any]] = []
        while queue and len(graph) < max_files:
            current, depth = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            imports = self._extract_imports(current)
            graph.append(
                {
                    "path": self._relative(current),
                    "depth": depth,
                    "imports": imports,
                }
            )
            if depth >= max_depth:
                continue
            for import_name in imports:
                resolved = self._resolve_import_to_file(current, import_name)
                if resolved is None or resolved in visited:
                    continue
                queue.append((resolved, depth + 1))
        return graph

    def _extract_imports(self, path: Path) -> list[str]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            return []
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                prefix = "." * node.level
                module = node.module or ""
                if module:
                    imports.append(prefix + module)
                else:
                    imports.extend(prefix + alias.name for alias in node.names)
        return sorted(set(imports))

    def _resolve_import_to_file(self, current_file: Path, import_name: str) -> Path | None:
        candidates: list[Path] = []
        if import_name.startswith("."):
            level = len(import_name) - len(import_name.lstrip("."))
            module_tail = import_name[level:]
            base = current_file.parent
            for _ in range(max(level - 1, 0)):
                base = base.parent
            if module_tail:
                candidates.append(base / Path(*module_tail.split(".")).with_suffix(".py"))
                candidates.append(base / Path(*module_tail.split(".")) / "__init__.py")
        else:
            candidates.append(self.repo_root / Path(*import_name.split(".")).with_suffix(".py"))
            candidates.append(self.repo_root / Path(*import_name.split(".")) / "__init__.py")
            candidates.append(self.repo_root / "literature_assistant" / "core" / Path(*import_name.split(".")).with_suffix(".py"))
            candidates.append(self.repo_root / "literature_assistant" / "core" / Path(*import_name.split(".")) / "__init__.py")
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            allowed, _ = self.policy.is_allowed(resolved)
            if resolved.exists() and resolved.is_file() and allowed:
                self.policy.reset_touched()
                return resolved
            self.policy.reset_touched()
        return None

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            return str(path)

    def _is_text_file(self, path: Path) -> bool:
        if path.suffix.lower() in TEXT_EXTENSIONS:
            return True
        try:
            sample = path.read_bytes()[:4096]
        except OSError:
            return False
        return b"\x00" not in sample

    def _symbol_from_node(self, node: ast.stmt) -> SourceSymbol | None:
        if isinstance(node, ast.ClassDef):
            return SourceSymbol(node.name, "class", node.lineno, getattr(node, "end_lineno", None))
        if isinstance(node, ast.AsyncFunctionDef):
            return SourceSymbol(node.name, "async_function", node.lineno, getattr(node, "end_lineno", None))
        if isinstance(node, ast.FunctionDef):
            return SourceSymbol(node.name, "function", node.lineno, getattr(node, "end_lineno", None))
        return None

    def _validate_positive_int(self, value: int, name: str, upper: int) -> None:
        if not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if value < 1 or value > upper:
            raise ValueError(f"{name} must be between 1 and {upper}")


def create_default_source_tools(repo_root: Path, audit: AuditLog | None = None) -> SourceTools:
    """Create SourceTools with the default repository policy."""
    if not repo_root.is_absolute():
        raise ValueError("repo_root must be absolute")
    policy = PathPolicy(
        repo_root=repo_root,
        allowed_roots=DEFAULT_ALLOWED_ROOTS,
        denied_patterns=DEFAULT_DENIED_PATTERNS,
    )
    return SourceTools(repo_root=repo_root, policy=policy, audit=audit)
