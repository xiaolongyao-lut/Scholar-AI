"""Dump PyInstaller Analysis input collection to JSON without producing onedir.

Why: Slice A0 release gate (DEC-006c, R3) needs to inspect what the spec is
about to feed PyInstaller — `datas` / `binaries` / `hiddenimports` / `pathex` /
`runtime_hooks` — before PyInstaller actually runs Analysis (which is slow
and triggers module graph resolution).

Approach: exec the spec file with `Analysis`, `PYZ`, `EXE`, `COLLECT`,
`BUNDLE`, `MERGE`, `Tree` replaced by capturing stubs so the spec runs to
completion without triggering PyInstaller. Capture Analysis() args and
expand any `Tree` invocations in the data list.

This is a *static* analysis: dynamic datas computed via os.path.join /
glob / list comprehension over filesystem state ARE captured because the
spec runs as Python; but datas added by PyInstaller hooks (which only run
during real Analysis) are NOT captured. The final onedir scan
(scripts/release_forbidden_path_scan.py) catches hook-injected files as
fact-gate, per plan v2 §13.2 constraint #8.

Usage:
    python scripts/dump_pyinstaller_analysis.py \
        --spec packaging/pyinstaller/literature-assistant.spec \
        --out workspace_artifacts/releases/<version>/build-manifests/pyinstaller-analysis-datas.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _normalize_toc_entry(entry: Any) -> dict[str, str]:
    """Coerce a spec-style (src, dest, [kind]) tuple-like into a dict.

    Note: spec files use (src, dest, [kind]) but PyInstaller's internal TOC
    uses (dest, src, kind). This dumper captures spec-input semantics.
    """
    if isinstance(entry, tuple):
        if len(entry) >= 3:
            return {"src": str(entry[0] or ""), "dest": str(entry[1] or ""), "kind": str(entry[2] or "")}
        if len(entry) == 2:
            return {"src": str(entry[0] or ""), "dest": str(entry[1] or ""), "kind": ""}
    return {"src": str(entry), "dest": "", "kind": ""}


def _normalize_toc_list(items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not items:
        return out
    for entry in items:
        out.append(_normalize_toc_entry(entry))
    return out


def _build_stubs(captured: dict[str, Any]) -> dict[str, Any]:
    class _Capture:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs
            # PyInstaller code that follows Analysis() reads attributes off it.
            # Fake the most common ones with empty lists so PYZ()/EXE()/COLLECT() chained calls don't crash.
            self.scripts = []
            self.pure = []
            self.zipped_data = []
            self.binaries = []
            self.datas = list(kwargs.get("datas", []) or [])
            self.zipfiles = []
            self.dependencies = []
            self.hiddenimports = list(kwargs.get("hiddenimports", []) or [])
            self.pathex = list(kwargs.get("pathex", []) or [])
            for arg in args:
                if isinstance(arg, list) and not self.scripts:
                    self.scripts = [{"src": str(a), "dest": "", "kind": "PYSOURCE"} for a in arg]

    class _TreeStub:
        """Tree(src, prefix=...) returns a list-like; record but do not walk."""

        def __init__(self, root: Any, prefix: str = "", excludes: Any = None, typecode: str = "DATA") -> None:
            self.root = str(root)
            self.prefix = prefix or ""
            self.excludes = list(excludes or [])
            self.typecode = typecode
            captured.setdefault("trees", []).append(
                {"root": self.root, "prefix": self.prefix, "excludes": self.excludes, "typecode": typecode}
            )

        def __iter__(self):
            # Make it iterable so `datas + Tree(...)` doesn't crash spec evaluation.
            return iter([])

        def __add__(self, other: Any) -> Any:
            return list(other) if isinstance(other, list) else []

        def __radd__(self, other: Any) -> Any:
            return list(other) if isinstance(other, list) else []

    def _analysis_factory(*args: Any, **kwargs: Any):
        instance = _Capture(*args, **kwargs)
        captured["analysis_args"] = list(args)
        captured["analysis_kwargs"] = dict(kwargs)
        captured["analysis_instance"] = instance
        return instance

    return {
        "Analysis": _analysis_factory,
        "PYZ": _Capture,
        "EXE": _Capture,
        "COLLECT": _Capture,
        "BUNDLE": _Capture,
        "MERGE": _Capture,
        "Tree": _TreeStub,
    }


def dump_manifest(spec_path: Path, output_path: Path) -> int:
    spec_text = spec_path.read_text(encoding="utf-8")
    captured: dict[str, Any] = {}
    stubs = _build_stubs(captured)
    workdir = Path(tempfile.mkdtemp(prefix="pyi_dump_"))
    spec_name = spec_path.stem
    spec_globals: dict[str, Any] = {
        "__name__": "__main__",
        "__file__": str(spec_path),
        "SPECPATH": str(spec_path.resolve().parent),
        "SPEC": str(spec_path.name),
        "specnm": spec_name,
        "workpath": str(workdir / "build" / spec_name),
        "distpath": str(workdir / "dist"),
        "DISTPATH": str(workdir / "dist"),
        "WARNFILE": str(workdir / f"warn-{spec_name}.txt"),
        "noconfirm": True,
    }
    spec_globals.update(stubs)

    try:
        compiled = compile(spec_text, str(spec_path), "exec")
        exec(compiled, spec_globals)  # noqa: S102 — controlled spec execution
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[dump] spec exec failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1

    if "analysis_kwargs" not in captured:
        print("[dump] Analysis() was not invoked by the spec", file=sys.stderr)
        return 1

    kwargs = captured["analysis_kwargs"]
    args = captured["analysis_args"]
    scripts_list = args[0] if args else kwargs.get("scripts", [])

    manifest: dict[str, Any] = {
        "schema_version": "pyinstaller_analysis_input.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "spec": str(spec_path.resolve()),
        "stage": "pyinstaller_analysis_input",
        "note": "Captures Analysis() input args. Hook-injected datas NOT included; final onedir scan covers them.",
        "scripts": [{"src": str(s), "dest": "", "kind": "PYSOURCE"} for s in (scripts_list or [])],
        "datas": _normalize_toc_list(kwargs.get("datas", [])),
        "binaries": _normalize_toc_list(kwargs.get("binaries", [])),
        "hiddenimports": list(kwargs.get("hiddenimports", []) or []),
        "pathex": [str(p) for p in (kwargs.get("pathex", []) or [])],
        "runtime_hooks": [str(p) for p in (kwargs.get("runtime_hooks", []) or [])],
        "excludes": list(kwargs.get("excludes", []) or []),
        "hookspath": [str(p) for p in (kwargs.get("hookspath", []) or [])],
        "trees": captured.get("trees", []),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[dump] wrote {output_path} "
        f"({len(manifest['datas'])} datas, {len(manifest['binaries'])} binaries, "
        f"{len(manifest['hiddenimports'])} hiddenimports)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump PyInstaller Analysis input as JSON.")
    parser.add_argument("--spec", required=True, type=Path, help="Path to .spec file.")
    parser.add_argument("--out", required=True, type=Path, help="Output JSON path.")
    args = parser.parse_args()
    return dump_manifest(args.spec.resolve(), args.out.resolve())


if __name__ == "__main__":
    sys.exit(main())
