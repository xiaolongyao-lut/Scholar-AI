"""Bounded Python sandbox for experimental local workflows."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from .redaction import SecretRedactor

MAX_CODE_CHARS: int = 16_000
MAX_INPUT_BYTES: int = 64 * 1024
MAX_OUTPUT_CHARS: int = 64_000
DEFAULT_TIMEOUT_SEC: int = 5
MAX_TIMEOUT_SEC: int = 20
SAFE_IMPORTS: frozenset[str] = frozenset(
    {
        "collections",
        "datetime",
        "functools",
        "itertools",
        "json",
        "math",
        "operator",
        "random",
        "re",
        "statistics",
        "string",
    }
)
BLOCKED_NAMES: frozenset[str] = frozenset(
    {
        "__builtins__",
        "__import__",
        "__loader__",
        "__spec__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "globals",
        "help",
        "input",
        "locals",
        "open",
        "quit",
        "vars",
    }
)
BLOCKED_ATTRS: frozenset[str] = frozenset(
    {
        "__class__",
        "__dict__",
        "__globals__",
        "__mro__",
        "__subclasses__",
        "__code__",
        "__closure__",
        "__func__",
        "__self__",
    }
)


class PythonSandbox:
    """Execute small pure-Python snippets in a restricted child process."""

    def __init__(
        self,
        python_executable: Path | None = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        """Create a sandbox runner.

        Args:
            python_executable: Python interpreter used for the child process.
            timeout_sec: Default child-process timeout in seconds.
        """
        if python_executable is not None and not isinstance(python_executable, Path):
            raise TypeError("python_executable must be a Path")
        self.python_executable = python_executable or Path(sys.executable)
        self.timeout_sec = _bounded_timeout(timeout_sec)

    def run(self, code: str, input_data: dict[str, Any] | None = None, timeout_sec: int | None = None) -> dict[str, Any]:
        """Run code with JSON input and JSON-serializable ``result`` output.

        Args:
            code: Python source. It may assign a variable named ``result``.
            input_data: JSON object exposed as ``input_data`` inside the child.
            timeout_sec: Optional per-run timeout, capped by ``MAX_TIMEOUT_SEC``.
        """
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")
        if len(code) > MAX_CODE_CHARS:
            raise ValueError(f"code exceeds {MAX_CODE_CHARS} characters")
        if input_data is None:
            input_data = {}
        if not isinstance(input_data, dict):
            raise ValueError("input_data must be an object")
        serialized_input = json.dumps(input_data, ensure_ascii=False)
        if len(serialized_input.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError(f"input_data exceeds {MAX_INPUT_BYTES} bytes")
        _validate_ast(code)

        timeout = _bounded_timeout(timeout_sec or self.timeout_sec)
        with tempfile.TemporaryDirectory(prefix="litassist-sandbox-") as tmp_dir:
            runner_path = Path(tmp_dir) / "runner.py"
            stdin_payload = json.dumps(
                {
                    "code": code,
                    "input_data": input_data,
                    "safe_imports": sorted(SAFE_IMPORTS),
                },
                ensure_ascii=False,
            )
            runner_path.write_text(_CHILD_RUNNER, encoding="utf-8")
            try:
                completed = subprocess.run(
                    [str(self.python_executable), str(runner_path)],
                    input=stdin_payload,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    cwd=tmp_dir,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return {
                    "ok": False,
                    "error_code": "python_sandbox_timeout",
                    "message": f"Python sandbox exceeded {timeout} seconds",
                    "stdout": "",
                    "stderr": "",
                    "result": None,
                }

        stdout = SecretRedactor.scan((completed.stdout or "")[:MAX_OUTPUT_CHARS])
        stderr = SecretRedactor.scan((completed.stderr or "")[:MAX_OUTPUT_CHARS])
        parsed: dict[str, Any] | None = None
        for line in reversed(stdout.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                candidate = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and candidate.get("__litassist_sandbox__") is True:
                parsed = candidate
                break
        if completed.returncode != 0 or parsed is None:
            return {
                "ok": False,
                "error_code": "python_sandbox_failed",
                "message": "Python sandbox process failed",
                "stdout": stdout,
                "stderr": stderr,
                "result": None,
            }
        return {
            "ok": bool(parsed.get("ok")),
            "error_code": parsed.get("error_code"),
            "message": parsed.get("message"),
            "stdout": stdout.replace(json.dumps(parsed, ensure_ascii=False), "").strip(),
            "stderr": stderr,
            "result": parsed.get("result"),
        }


class SandboxAstGuard(ast.NodeVisitor):
    """Reject AST nodes that can reach filesystem, shell, or introspection."""

    def visit_Import(self, node: ast.Import) -> None:
        """Validate import statements against the explicit allowlist."""
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root not in SAFE_IMPORTS:
                raise ValueError(f"import not allowed: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Validate from-import statements against the explicit allowlist."""
        if node.module is None:
            raise ValueError("relative imports are not allowed")
        root = node.module.split(".", 1)[0]
        if root not in SAFE_IMPORTS:
            raise ValueError(f"import not allowed: {node.module}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Block direct access to dangerous builtins and interpreter hooks."""
        if node.id in BLOCKED_NAMES:
            raise ValueError(f"name not allowed: {node.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Block object graph escape attributes."""
        if node.attr in BLOCKED_ATTRS or node.attr.startswith("__"):
            raise ValueError(f"attribute not allowed: {node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Block known dangerous call targets even through attribute syntax."""
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_NAMES:
            raise ValueError(f"call not allowed: {node.func.id}")
        if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_ATTRS:
            raise ValueError(f"call not allowed: {node.func.attr}")
        self.generic_visit(node)


def _validate_ast(code: str) -> None:
    """Validate code before passing it to the child process."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"invalid Python syntax: {exc}") from exc
    SandboxAstGuard().visit(tree)


def _bounded_timeout(value: int) -> int:
    """Normalize sandbox timeout values."""
    if not isinstance(value, int):
        raise ValueError("timeout_sec must be an integer")
    if value < 1 or value > MAX_TIMEOUT_SEC:
        raise ValueError(f"timeout_sec must be between 1 and {MAX_TIMEOUT_SEC}")
    return value


_CHILD_RUNNER = textwrap.dedent(
    r'''
    from __future__ import annotations

    import builtins
    import importlib
    import json
    import sys
    import traceback

    payload = json.loads(sys.stdin.read())
    code = payload["code"]
    input_data = payload["input_data"]
    safe_imports = set(payload["safe_imports"])

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = str(name).split(".", 1)[0]
        if level != 0 or root not in safe_imports:
            raise ImportError(f"import not allowed: {name}")
        return importlib.import_module(name)

    allowed_builtin_names = {
        "abs", "all", "any", "bool", "chr", "dict", "divmod", "enumerate",
        "filter", "float", "format", "hash", "hex", "int", "isinstance",
        "issubclass", "len", "list", "map", "max", "min", "next", "ord",
        "pow", "print", "range", "repr", "reversed", "round", "set", "slice",
        "sorted", "str", "sum", "tuple", "zip",
    }
    safe_builtins = {name: getattr(builtins, name) for name in allowed_builtin_names}
    safe_builtins["__import__"] = guarded_import
    env = {
        "__builtins__": safe_builtins,
        "input_data": input_data,
    }

    try:
        exec(compile(code, "<litassist-python-sandbox>", "exec"), env, env)
        result = env.get("result")
        json.dumps(result, ensure_ascii=False)
        print(json.dumps({
            "__litassist_sandbox__": True,
            "ok": True,
            "error_code": None,
            "message": None,
            "result": result,
        }, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({
            "__litassist_sandbox__": True,
            "ok": False,
            "error_code": "python_sandbox_exception",
            "message": f"{type(exc).__name__}: {exc}",
            "result": None,
        }, ensure_ascii=False))
        traceback.print_exc(file=sys.stderr)
    '''
).lstrip()
