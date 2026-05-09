from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _repo_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _write_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON through a same-directory temporary file to avoid partial manifests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            tmp_name = handle.name
        os.replace(tmp_name, path)
    finally:
        if tmp_name is not None:
            tmp_path = Path(tmp_name)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass


def _temporary_candidate_path(path: Path) -> Path:
    """Return a same-directory validation path that is not the final manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.candidate.",
        suffix=".json",
        delete=False,
    )
    handle.close()
    candidate = Path(handle.name)
    candidate.unlink(missing_ok=True)
    return candidate


def _count_nonempty_lines(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Manifest root must be a JSON object")
    return payload


def _remove_if_exists(log_path: Path, path: Path | None) -> None:
    if path is None:
        return
    if path.exists():
        path.unlink()
        _write_log(log_path, f"removed_stale_output {path}")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _require_mapping(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    value = manifest.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Manifest section {key!r} must be an object")
    return value


def _required_repo_path(section: dict[str, Any], key: str, *, must_exist: bool = False) -> Path:
    raw_value = section.get(key)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise RuntimeError(f"Manifest is missing required path field {key!r}")
    resolved = _repo_path(raw_value)
    if resolved is None:
        raise RuntimeError(f"Manifest path field {key!r} could not be resolved")
    if must_exist and not resolved.exists():
        raise RuntimeError(f"Manifest path field {key!r} does not exist: {raw_value!r}")
    return resolved


def _optional_nonnegative_int(section: dict[str, Any], key: str) -> int | None:
    value = section.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise RuntimeError(f"Manifest field {key!r} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Manifest field {key!r} must be an integer") from exc
    if parsed < 0:
        raise RuntimeError(f"Manifest field {key!r} must be non-negative")
    return parsed


def _optional_bool(section: dict[str, Any], key: str, *, default: bool | None = None) -> bool | None:
    value = section.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Manifest field {key!r} must be a boolean")


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _safe_run_id(raw_value: str) -> str:
    run_id = str(raw_value or "").strip()
    if not run_id:
        raise RuntimeError("run_id must be a non-empty string")
    if any(separator in run_id for separator in ("/", "\\")) or run_id in {".", ".."}:
        raise RuntimeError("run_id must be a filename-safe identifier, not a path")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if any(char not in allowed for char in run_id):
        raise RuntimeError("run_id may only contain letters, digits, dot, underscore, and dash")
    return run_id


def _manifest_output_paths(output_dir: Path, prefix: str) -> dict[str, str]:
    return {
        "metrics_path": _display_path(output_dir / f"{prefix}.metrics.json"),
        "progress_path": _display_path(output_dir / f"{prefix}.progress.jsonl"),
        "per_query_output": _display_path(output_dir / f"{prefix}.per_query.jsonl"),
        "rerank_trace_output": _display_path(output_dir / f"{prefix}.rerank_trace.jsonl"),
        "resume_guard_path": _display_path(output_dir / f"{prefix}.metrics.json.resume_config.json"),
        "run_log_path": _display_path(output_dir / f"{prefix}.run.log"),
    }


def _validate_output_paths(outputs: dict[str, Any], *, required_keys: list[str]) -> dict[str, Path]:
    output_paths = {key: _required_repo_path(outputs, key) for key in required_keys}
    output_path_texts = [str(path.resolve()) for path in output_paths.values()]
    duplicate_outputs = sorted(
        path for path in set(output_path_texts) if output_path_texts.count(path) > 1
    )
    if duplicate_outputs:
        raise RuntimeError(f"Manifest output paths must be unique: {duplicate_outputs}")
    return output_paths


def _validate_rerank_target(
    *,
    retrieval_config: dict[str, Any],
    runtime_env_overrides: dict[str, Any],
    reranker: dict[str, Any],
    require_runtime_rerank_opt_in: bool,
) -> dict[str, Any]:
    if _optional_bool(retrieval_config, "use_rerank", default=False) is not True:
        raise RuntimeError("Pinned rerank manifest must set retrieval_config.use_rerank=true")

    target_base_url = str(
        runtime_env_overrides.get("DASHSCOPE_RERANK_BASE_URL")
        or runtime_env_overrides.get("SILICONFLOW_RERANK_BASE_URL")
        or ""
    ).strip()
    target_model = str(
        runtime_env_overrides.get("DASHSCOPE_RERANK_MODEL")
        or runtime_env_overrides.get("SILICONFLOW_RERANK_MODEL")
        or reranker.get("model")
        or ""
    ).strip()
    if not target_base_url or not target_model:
        raise RuntimeError("Manifest must pin rerank base_url and model")

    runtime_opt_in = _truthy(runtime_env_overrides.get("RAG_RUNTIME_RERANK_ENABLED"))
    if require_runtime_rerank_opt_in and not runtime_opt_in:
        raise RuntimeError("Manifest must set runtime_env_overrides.RAG_RUNTIME_RERANK_ENABLED=1")

    return {
        "base_url": target_base_url,
        "model": target_model,
        "provider": "dashscope" if "dashscope" in target_base_url.lower() else "siliconflow",
        "runtime_rerank_opt_in": runtime_opt_in,
    }


def _validate_control_manifest(
    manifest: dict[str, Any],
    rerank_inputs: dict[str, Any],
    rerank_outputs: dict[str, Path],
) -> dict[str, Any] | None:
    control = manifest.get("paired_control")
    safety = manifest.get("safety") or {}
    if not isinstance(safety, dict):
        raise RuntimeError("Manifest section 'safety' must be an object when present")
    if control is None:
        if _optional_bool(safety, "requires_paired_no_rerank_control", default=False):
            raise RuntimeError("Manifest safety.requires_paired_no_rerank_control=true requires paired_control")
        return None
    if not isinstance(control, dict):
        raise RuntimeError("Manifest section 'paired_control' must be an object")

    control_inputs = _require_mapping(control, "inputs")
    control_outputs = _require_mapping(control, "outputs")
    control_retrieval_config = _require_mapping(control, "retrieval_config")
    control_runtime_env = control.get("runtime_env_overrides") or {}
    if not isinstance(control_runtime_env, dict):
        raise RuntimeError("Control runtime_env_overrides must be an object when present")

    rerank_queries_path = _required_repo_path(rerank_inputs, "queries_path", must_exist=True)
    rerank_qrels_path = _required_repo_path(rerank_inputs, "qrels_path", must_exist=True)
    control_queries_path = _required_repo_path(control_inputs, "queries_path", must_exist=True)
    control_qrels_path = _required_repo_path(control_inputs, "qrels_path", must_exist=True)
    if control_queries_path.resolve() != rerank_queries_path.resolve():
        raise RuntimeError("Control queries_path must match rerank manifest inputs.queries_path")
    if control_qrels_path.resolve() != rerank_qrels_path.resolve():
        raise RuntimeError("Control qrels_path must match rerank manifest inputs.qrels_path")

    expected_queries = _optional_nonnegative_int(rerank_inputs, "queries_nonempty_lines")
    control_expected_queries = _optional_nonnegative_int(control_inputs, "queries_nonempty_lines")
    if expected_queries is not None and control_expected_queries != expected_queries:
        raise RuntimeError("Control queries_nonempty_lines must match rerank manifest")
    expected_qrels = _optional_nonnegative_int(rerank_inputs, "qrels_nonempty_lines")
    control_expected_qrels = _optional_nonnegative_int(control_inputs, "qrels_nonempty_lines")
    if expected_qrels is not None and control_expected_qrels != expected_qrels:
        raise RuntimeError("Control qrels_nonempty_lines must match rerank manifest")

    if "use_rerank" not in control_retrieval_config:
        raise RuntimeError("Control retrieval_config.use_rerank must be set explicitly")
    if _optional_bool(control_retrieval_config, "use_rerank") is not False:
        raise RuntimeError("Control retrieval_config.use_rerank must be false")
    if _truthy(control_runtime_env.get("RAG_RUNTIME_RERANK_ENABLED")):
        raise RuntimeError("Control runtime_env_overrides.RAG_RUNTIME_RERANK_ENABLED must not be truthy")

    comparable_keys = [
        "top_k",
        "recall_top_n",
        "use_prefilter",
        "prefilter_threshold",
        "use_dynamic_topk",
        "dynamic_low_rerank_top_n",
        "dynamic_high_rerank_top_n",
        "dynamic_score_gap_threshold",
        "use_expansion",
        "use_contextual",
        "query_concurrency",
        "strict_cache_guard",
    ]
    rerank_retrieval_config = _require_mapping(manifest, "retrieval_config")
    for key in comparable_keys:
        if key in rerank_retrieval_config and control_retrieval_config.get(key) != rerank_retrieval_config.get(key):
            raise RuntimeError(f"Control retrieval_config.{key} must match rerank manifest")

    output_keys = [
        "metrics_path",
        "progress_path",
        "per_query_output",
        "rerank_trace_output",
        "resume_guard_path",
        "run_log_path",
    ]
    control_output_paths = _validate_output_paths(control_outputs, required_keys=output_keys)
    rerank_output_path_texts = {str(path.resolve()) for path in rerank_outputs.values()}
    overlapping_outputs = sorted(
        _display_path(path)
        for path in control_output_paths.values()
        if str(path.resolve()) in rerank_output_path_texts
    )
    if overlapping_outputs:
        raise RuntimeError(f"Control output paths must not overlap rerank outputs: {overlapping_outputs}")
    stale_outputs = [
        _display_path(path)
        for path in control_output_paths.values()
        if path.exists()
    ]
    return {
        "queries_path": str(control_queries_path),
        "qrels_path": str(control_qrels_path),
        "retrieval_config": {
            "use_rerank": False,
            "top_k": control_retrieval_config.get("top_k"),
            "query_concurrency": control_retrieval_config.get("query_concurrency"),
        },
        "output_paths": {
            key: _display_path(path)
            for key, path in control_output_paths.items()
        },
        "stale_outputs": stale_outputs,
        "status": "ok",
    }


def dry_run_manifest(manifest_path: Path, *, require_runtime_rerank_opt_in: bool = False) -> dict[str, Any]:
    """Validate a pinned rerank manifest without invoking models or mutating files.

    Args:
        manifest_path: Manifest JSON path.
        require_runtime_rerank_opt_in: When true, require the runtime opt-in
            guard used by RAG canary runs.

    Returns:
        A JSON-safe preflight report for humans, agents, and CI.
    """
    manifest = _load_manifest(manifest_path)
    inputs = _require_mapping(manifest, "inputs")
    outputs = _require_mapping(manifest, "outputs")
    retrieval_config = _require_mapping(manifest, "retrieval_config")
    runtime_env_overrides = _require_mapping(manifest, "runtime_env_overrides")
    reranker = _require_mapping(manifest, "reranker")

    queries_path = _required_repo_path(inputs, "queries_path", must_exist=True)
    qrels_path = _required_repo_path(inputs, "qrels_path", must_exist=True)
    queries_nonempty_lines = _count_nonempty_lines(queries_path)
    qrels_nonempty_lines = _count_nonempty_lines(qrels_path)

    expected_queries = _optional_nonnegative_int(inputs, "queries_nonempty_lines")
    if expected_queries is not None and queries_nonempty_lines != expected_queries:
        raise RuntimeError(
            "Manifest inputs.queries_nonempty_lines mismatch: "
            f"expected={expected_queries} actual={queries_nonempty_lines}"
        )
    expected_qrels = _optional_nonnegative_int(inputs, "qrels_nonempty_lines")
    if expected_qrels is not None and qrels_nonempty_lines != expected_qrels:
        raise RuntimeError(
            "Manifest inputs.qrels_nonempty_lines mismatch: "
            f"expected={expected_qrels} actual={qrels_nonempty_lines}"
        )

    output_keys = [
        "metrics_path",
        "progress_path",
        "per_query_output",
        "rerank_trace_output",
        "resume_guard_path",
        "run_log_path",
    ]
    output_paths = _validate_output_paths(outputs, required_keys=output_keys)
    pinned_reranker = _validate_rerank_target(
        retrieval_config=retrieval_config,
        runtime_env_overrides=runtime_env_overrides,
        reranker=reranker,
        require_runtime_rerank_opt_in=require_runtime_rerank_opt_in,
    )
    control_report = _validate_control_manifest(manifest, inputs, output_paths)

    stale_outputs = [
        _display_path(path)
        for path in output_paths.values()
        if path.exists()
    ]

    return {
        "manifest_path": str(manifest_path),
        "queries_path": str(queries_path),
        "qrels_path": str(qrels_path),
        "queries_nonempty_lines": queries_nonempty_lines,
        "qrels_nonempty_lines": qrels_nonempty_lines,
        "retrieval_config": {
            "use_rerank": bool(_optional_bool(retrieval_config, "use_rerank", default=False)),
            "top_k": retrieval_config.get("top_k"),
            "rerank_top_n": retrieval_config.get("rerank_top_n"),
            "query_concurrency": retrieval_config.get("query_concurrency"),
        },
        "pinned_reranker": {
            "base_url": pinned_reranker["base_url"],
            "model": pinned_reranker["model"],
            "provider": pinned_reranker["provider"],
        },
        "runtime_rerank_opt_in": bool(pinned_reranker["runtime_rerank_opt_in"]),
        "output_paths": {
            key: _display_path(path)
            for key, path in output_paths.items()
        },
        "paired_control": control_report,
        "stale_outputs": stale_outputs,
        "status": "ok",
    }


def materialize_dated_manifest(
    template_path: Path,
    *,
    run_id: str,
    output_manifest: Path | None = None,
    output_dir: Path | None = None,
    force: bool = False,
    require_runtime_rerank_opt_in: bool = True,
) -> dict[str, Any]:
    """Create a dated rerank manifest from a safe template and validate it.

    Args:
        template_path: Existing template manifest path.
        run_id: Filename-safe run identifier used in output artifact names.
        output_manifest: Optional destination manifest path.
        output_dir: Optional artifact directory for metrics/progress/per-query files.
        force: Allow replacing an existing destination manifest.
        require_runtime_rerank_opt_in: Pass-through validation guard.

    Returns:
        JSON-safe report containing destination paths and dry-run preflight.
    """
    safe_run_id = _safe_run_id(run_id)
    manifest = _load_manifest(template_path)
    destination = output_manifest or (REPO_ROOT / "workspace_artifacts" / "generated" / "eval" / "manifests" / f"{safe_run_id}.json")
    destination = destination if destination.is_absolute() else REPO_ROOT / destination
    if destination.exists() and not force:
        raise RuntimeError(f"Destination manifest already exists: {_display_path(destination)}")

    artifact_dir = output_dir or (REPO_ROOT / "workspace_artifacts" / "generated" / "eval" / safe_run_id)
    artifact_dir = artifact_dir if artifact_dir.is_absolute() else REPO_ROOT / artifact_dir
    manifest["schema_version"] = str(manifest.get("schema_version") or "1")
    manifest["materialized_from"] = _display_path(template_path)
    manifest["materialized_run_id"] = safe_run_id
    manifest["materialized_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    outputs = _require_mapping(manifest, "outputs")
    outputs.clear()
    outputs.update(_manifest_output_paths(artifact_dir, safe_run_id))

    control = manifest.get("paired_control")
    if isinstance(control, dict):
        control_outputs = _require_mapping(control, "outputs")
        control_outputs.clear()
        control_outputs.update(_manifest_output_paths(artifact_dir, f"{safe_run_id}-no-rerank-control"))

    safety = manifest.setdefault("safety", {})
    if not isinstance(safety, dict):
        raise RuntimeError("Manifest section 'safety' must be an object when present")
    safety["requires_paired_no_rerank_control"] = True
    safety["requires_unique_output_paths"] = True

    candidate = _temporary_candidate_path(destination)
    try:
        _atomic_write_json(candidate, manifest)
        preflight = dry_run_manifest(
            candidate,
            require_runtime_rerank_opt_in=require_runtime_rerank_opt_in,
        )
        os.replace(candidate, destination)
        preflight = dry_run_manifest(
            destination,
            require_runtime_rerank_opt_in=require_runtime_rerank_opt_in,
        )
    except Exception:
        if candidate.exists():
            candidate.unlink()
        raise

    return {
        "status": "ok",
        "run_id": safe_run_id,
        "manifest_path": _display_path(destination),
        "output_dir": _display_path(artifact_dir),
        "dry_run": preflight,
    }


def _select_pinned_candidate(target_base_url: str, target_model: str) -> tuple[str, str, str, str, str]:
    import reranker_client as rc

    ordered_candidates = getattr(rc, "_ordered_rerank_candidates")
    candidates = ordered_candidates(base_url=target_base_url, model=target_model)
    exact_matches = [
        candidate
        for candidate in candidates
        if str(candidate[1]).strip() == target_base_url and str(candidate[2]).strip() == target_model
    ]
    if not exact_matches:
        raise RuntimeError(f"No viable rerank candidate matched base_url={target_base_url!r} model={target_model!r}")

    api_key, base_url, model, source = exact_matches[0]
    provider = "dashscope" if rc.is_dashscope_rerank_url(base_url) else "unknown"
    return api_key, base_url, model, source, provider


def _patch_rerank_resolution(selected_api_key: str, selected_base_url: str, selected_model: str, selected_source: str) -> None:
    import reranker_client as rc

    def _single_candidates(
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
    ) -> list[tuple[str, str, str, str]]:
        if api_key is not None:
            return [(str(api_key), selected_base_url, selected_model, "explicit")]
        _ = base_url, model
        return [(selected_api_key, selected_base_url, selected_model, f"pinned:{selected_source}")]

    def _single_ordered(
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        probe_candidates: bool = True,
    ) -> list[tuple[str, str, str, str]]:
        _ = probe_candidates
        return _single_candidates(api_key, base_url=base_url, model=model)

    def _single_config(
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
    ) -> tuple[str | None, str, str]:
        _ = base_url, model
        if api_key is not None:
            return str(api_key), selected_base_url, selected_model
        return selected_api_key, selected_base_url, selected_model

    rc.resolve_rerank_candidates = _single_candidates
    setattr(rc, "_ordered_rerank_candidates", _single_ordered)
    rc.resolve_rerank_config = _single_config


def run_manifest(manifest_path: Path) -> int:
    dry_run_manifest(manifest_path)
    manifest = _load_manifest(manifest_path)
    outputs = manifest.get("outputs") or {}
    retrieval_config = manifest.get("retrieval_config") or {}
    runtime_env_overrides = manifest.get("runtime_env_overrides") or {}
    inputs = manifest.get("inputs") or {}
    reranker = manifest.get("reranker") or {}

    run_log_path = _repo_path(str(outputs.get("run_log_path") or ""))
    if run_log_path is None:
        raise RuntimeError("Manifest is missing outputs.run_log_path")
    if run_log_path.exists():
        run_log_path.unlink()

    metrics_path = _repo_path(str(outputs.get("metrics_path") or ""))
    progress_path = _repo_path(str(outputs.get("progress_path") or ""))
    per_query_path = _repo_path(str(outputs.get("per_query_output") or ""))
    rerank_trace_path = _repo_path(str(outputs.get("rerank_trace_output") or ""))
    resume_guard_path = _repo_path(str(outputs.get("resume_guard_path") or ""))

    queries_path = _repo_path(str(inputs.get("queries_path") or ""))
    qrels_path = _repo_path(str(inputs.get("qrels_path") or ""))
    if queries_path is None or not queries_path.exists():
        raise RuntimeError(f"Queries path missing: {inputs.get('queries_path')!r}")
    if qrels_path is None or not qrels_path.exists():
        raise RuntimeError(f"Qrels path missing: {inputs.get('qrels_path')!r}")

    _write_log(run_log_path, f"manifest_preflight_ok queries={queries_path.name} qrels={qrels_path.name}")
    for candidate in (metrics_path, progress_path, per_query_path, rerank_trace_path, resume_guard_path):
        _remove_if_exists(run_log_path, candidate)

    for key, value in runtime_env_overrides.items():
        if isinstance(value, str) and value.startswith("derived-at-runtime"):
            continue
        if key == "process_patch":
            continue
        os.environ[str(key)] = str(value)

    target_base_url = str(
        runtime_env_overrides.get("DASHSCOPE_RERANK_BASE_URL")
        or runtime_env_overrides.get("SILICONFLOW_RERANK_BASE_URL")
        or ""
    )
    target_model = str(
        runtime_env_overrides.get("DASHSCOPE_RERANK_MODEL")
        or runtime_env_overrides.get("SILICONFLOW_RERANK_MODEL")
        or reranker.get("model")
        or ""
    )
    if not target_base_url or not target_model:
        raise RuntimeError("Manifest is missing pinned rerank base_url/model overrides")

    selected_api_key, selected_base_url, selected_model, selected_source, provider = _select_pinned_candidate(
        target_base_url,
        target_model,
    )
    _write_log(
        run_log_path,
        "selected_pinned_rerank "
        f"provider={provider} model={selected_model} base_url={selected_base_url} "
        f"key_len={len(selected_api_key)} key_suffix=***{selected_api_key[-4:]}",
    )

    _patch_rerank_resolution(selected_api_key, selected_base_url, selected_model, selected_source)

    from eval_retrieval_runtime import run_eval

    _write_log(run_log_path, "starting_run_eval")
    started = time.perf_counter()
    payload = run_eval(
        queries_path=str(inputs.get("queries_path")),
        output_path=str(outputs.get("metrics_path")),
        top_k=int(retrieval_config.get("top_k", 5)),
        recall_top_n=int(retrieval_config.get("recall_top_n", 100)),
        use_rerank=bool(retrieval_config.get("use_rerank", True)),
        rerank_top_n=int(retrieval_config.get("rerank_top_n", 40)),
        use_prefilter=bool(retrieval_config.get("use_prefilter", False)),
        prefilter_threshold=float(retrieval_config.get("prefilter_threshold", 0.3)),
        use_dynamic_topk=bool(retrieval_config.get("use_dynamic_topk", False)),
        dynamic_low_rerank_top_n=int(retrieval_config.get("dynamic_low_rerank_top_n", 20)),
        dynamic_high_rerank_top_n=int(retrieval_config.get("dynamic_high_rerank_top_n", 60)),
        dynamic_score_gap_threshold=float(retrieval_config.get("dynamic_score_gap_threshold", 0.15)),
        use_expansion=bool(retrieval_config.get("use_expansion", False)),
        use_contextual=bool(retrieval_config.get("use_contextual", False)),
        query_concurrency=int(retrieval_config.get("query_concurrency", 16)),
        strict_cache_guard=bool(retrieval_config.get("strict_cache_guard", True)),
        template_flags_path=inputs.get("template_flags_path"),
        offset=int(inputs.get("offset", 0)),
        limit=inputs.get("limit"),
        progress_path=str(outputs.get("progress_path")),
        progress_every=1,
        per_query_output=str(outputs.get("per_query_output")),
        rerank_trace_output=str(outputs.get("rerank_trace_output")),
    )
    elapsed = time.perf_counter() - started
    metric_payload = payload.get("aggregated_metrics") if isinstance(payload.get("aggregated_metrics"), dict) else payload
    _write_log(
        run_log_path,
        "run_eval_complete "
        f"elapsed_s={elapsed:.2f} recall_at_5={metric_payload.get('recall_at_5')} "
        f"mrr={metric_payload.get('mrr')} avg_latency_ms={metric_payload.get('avg_latency_ms')} "
        f"p95_latency_ms={metric_payload.get('p95_latency_ms')} rerank_api_avg_ms={metric_payload.get('rerank_api_avg_ms')}",
    )

    progress_count = _count_nonempty_lines(progress_path)
    per_query_count = _count_nonempty_lines(per_query_path)
    rerank_trace_count = _count_nonempty_lines(rerank_trace_path)
    _write_log(
        run_log_path,
        f"output_counts per_query={per_query_count} rerank_trace={rerank_trace_count} progress={progress_count}",
    )

    if resume_guard_path is None or not resume_guard_path.exists():
        raise RuntimeError("Resume guard file missing after run")
    resume_guard = json.loads(resume_guard_path.read_text(encoding="utf-8"))
    rerank_model = (((resume_guard.get("retrieval_config") or {}).get("rerank_model")) or "")
    _write_log(run_log_path, f"resume_guard_rerank_model={rerank_model}")

    expected_queries = int(inputs.get("queries_nonempty_lines") or 0)
    if expected_queries and not (
        progress_count == expected_queries and per_query_count == expected_queries and rerank_trace_count == expected_queries
    ):
        raise RuntimeError(
            f"Output line counts do not match expected query count: expected={expected_queries} progress={progress_count} per_query={per_query_count} rerank_trace={rerank_trace_count}"
        )
    if rerank_model != selected_model:
        raise RuntimeError(f"Resume guard rerank model mismatch: expected={selected_model!r} actual={rerank_model!r}")

    _write_log(run_log_path, "postrun_validation_ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a pinned rerank eval from an eval audit manifest.")
    parser.add_argument("manifest", help="Path to the eval manifest JSON file.")
    parser.add_argument("--dry-run", action="store_true", help="Validate manifest and print a JSON preflight report without invoking models.")
    parser.add_argument("--require-runtime-rerank-opt-in", action="store_true", help="Require RAG_RUNTIME_RERANK_ENABLED=1 in runtime_env_overrides during dry-run.")
    parser.add_argument("--materialize-dated", action="store_true", help="Create a dated rerank+control manifest from the template, then validate it without invoking models.")
    parser.add_argument("--run-id", help="Filename-safe run identifier for --materialize-dated.")
    parser.add_argument("--output-manifest", help="Optional destination path for --materialize-dated.")
    parser.add_argument("--output-dir", help="Optional artifact directory for materialized output paths.")
    parser.add_argument("--force", action="store_true", help="Allow --materialize-dated to replace an existing destination manifest.")
    args = parser.parse_args()
    manifest_path = _repo_path(args.manifest)
    if manifest_path is None or not manifest_path.exists():
        raise RuntimeError(f"Manifest not found: {args.manifest!r}")
    if args.materialize_dated:
        if not args.run_id:
            raise RuntimeError("--materialize-dated requires --run-id")
        report = materialize_dated_manifest(
            manifest_path,
            run_id=str(args.run_id),
            output_manifest=_repo_path(args.output_manifest) if args.output_manifest else None,
            output_dir=_repo_path(args.output_dir) if args.output_dir else None,
            force=bool(args.force),
            require_runtime_rerank_opt_in=bool(args.require_runtime_rerank_opt_in),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.dry_run:
        report = dry_run_manifest(
            manifest_path,
            require_runtime_rerank_opt_in=bool(args.require_runtime_rerank_opt_in),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    return run_manifest(manifest_path)


if __name__ == "__main__":
    raise SystemExit(main())
