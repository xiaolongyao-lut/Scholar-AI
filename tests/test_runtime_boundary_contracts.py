"""Behavior contracts for runtime data-shape boundaries."""

from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace, TracebackType
from typing import Any, Callable

import pytest
from fastapi import FastAPI

from agent_roles import format_discussion_context
import chunking_pipeline
from discussion_bus import AgentRole
from event_integration_layer import RuntimeEventHook
import feature_flags
from evolution.inspiration_capture import _ref_to_dict as inspiration_ref_to_dict
from evolution.rag_capture import _ref_to_dict as rag_ref_to_dict
from harness_canonical_events import CanonicalEvent
from hybrid_search_runtime import load_json as load_hybrid_json
from literature_assistant.core.local_citation_scope import (
    LocalCitationResolution as CanonicalLocalCitationResolution,
)
from literature_assistant.core.linter.rules.detect_duplicates import NoDuplicateDoi
from literature_assistant.core.mcp_runtime.accessors import (
    _resolve_server,
    get_enabled_server,
)
from literature_assistant.core.mcp_runtime.server_store import (
    RuntimeMcpServerStore as CanonicalRuntimeMcpServerStore,
)
from literature_assistant.core.models.mcp import (
    McpApprovalState as CanonicalMcpApprovalState,
    McpProvenance as CanonicalMcpProvenance,
    McpServerConfig as CanonicalMcpServerConfig,
    McpServerConfigCreate as CanonicalMcpServerConfigCreate,
    McpServerConfigUpdate as CanonicalMcpServerConfigUpdate,
    McpStdioConfig as CanonicalMcpStdioConfig,
    McpTransport as CanonicalMcpTransport,
)
from literature_assistant.core.models import PdfBboxUnit, pdf_bbox_matches_unit
from literature_assistant.core.runtime_env import wiki_enabled
from literature_assistant.core.wiki.evidence_adapter import coerce_evidence_reference
from manifest_builder import load_json as load_manifest_json
from material_bundler import load_json as load_material_json
from memory_fact_store import ExecutionFactRule, MemoryFactStore, TemporalFact
from memory_policy import MemoryPolicyEngine
from modules.cache_manager import CacheManager, cached
import recovery_autopilot_cli
from recovery_autopilot_control_plane import AutopilotControlPlane
from recovery_console import RecoveryConsole
from recovery_metrics_exporter import RecoveryMetricsCollector
import recovery_telemetry
from routers import intelligent_chat_router


def _isolated_python_env(root: Path) -> dict[str, str]:
    """Build a credential-free environment for import-identity subprocesses."""

    root.mkdir(parents=True, exist_ok=True)
    env = {
        name: value
        for name in ("COMSPEC", "SYSTEMDRIVE", "SYSTEMROOT", "WINDIR")
        if (value := os.environ.get(name))
    }
    env.update(
        {
            "APPDATA": str(root / "appdata"),
            "EMBEDDING_KEY_PROBE_DISABLE": "1",
            "HOME": str(root),
            "LITASSIST_DISABLE_FILE_LOG": "1",
            "LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT": str(root / "runtime"),
            "LITERATURE_ASSISTANT_USER_ROOT": str(root / "user"),
            "LITERATURE_DISABLE_KEY_POOL": "1",
            "LOCALAPPDATA": str(root / "localappdata"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "RERANK_KEY_PROBE_DISABLE": "1",
            "RUNTIME_ENV_DISABLE_DOTENV": "1",
            "TEMP": str(root),
            "TMP": str(root),
            "USERPROFILE": str(root),
            "WRITING_RUNTIME_STORAGE_ROOT": str(root / "writing"),
        }
    )
    return env


@pytest.mark.parametrize("import_mode", ["canonical", "flat"])
def test_strict_boundary_types_remain_compatible_in_each_import_mode(
    import_mode: str,
    tmp_path: Path,
) -> None:
    """Model-bearing boundaries must keep compatible types in either import mode.

    Legacy runtime modules may still retain flat transitive imports; this contract
    does not claim process-wide canonical module uniqueness.
    """

    repo_root = Path(__file__).resolve().parents[1]
    script = r"""
import importlib
import os
import sys
from pathlib import Path
from typing import get_type_hints

mode = sys.argv[1]
repo_root = Path(sys.argv[2]).resolve()
core_root = repo_root / "literature_assistant" / "core"
for entry in (str(repo_root), str(core_root)):
    while entry in sys.path:
        sys.path.remove(entry)
if mode == "canonical":
    sys.path.insert(0, str(repo_root))
    sys.path.insert(1, str(core_root))
    prefix = "literature_assistant.core."
else:
    sys.path.insert(0, str(core_root))
    sys.path.insert(1, str(repo_root))
    prefix = ""

assert not any(name.endswith(("_API_KEY", "_TOKEN", "_SECRET")) for name in os.environ)
assert not {"ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"} & set(os.environ)

chunk_models = importlib.import_module(f"{prefix}chunk_models")
chunking = importlib.import_module(f"{prefix}chunking_pipeline")
evidence_packer = importlib.import_module(f"{prefix}evidence_packer")
rag_workflow = importlib.import_module(f"{prefix}main_rag_workflow")
harness_protocols = importlib.import_module(f"{prefix}harness_protocols")
writing_runtime = importlib.import_module(f"{prefix}writing_runtime")
provider_rate_limit = importlib.import_module(f"{prefix}provider_rate_limit")
vector_store = importlib.import_module(f"{prefix}chunk_vector_store")
endpoint_policy = importlib.import_module(f"{prefix}provider_endpoint_policy")

assert chunking.EnrichedChunk is chunk_models.EnrichedChunk
assert rag_workflow.EvidenceReference is evidence_packer.EvidenceReference
assert writing_runtime.WritingJob is harness_protocols.WritingJob
assert vector_store.provider_rate_limit is provider_rate_limit
assert get_type_hints(chunking.ChunkingPipeline.run)["return"].__args__[0] is chunk_models.EnrichedChunk
assert get_type_hints(writing_runtime.JobExecutionContext)["job"] is harness_protocols.WritingJob

endpoint_policy.classify_ip("8.8.8.8")
if mode == "canonical":
    assert "literature_assistant.core.ip_guard" in sys.modules
    assert "ip_guard" not in sys.modules
else:
    assert "ip_guard" in sys.modules
    assert "literature_assistant.core.ip_guard" not in sys.modules
"""
    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            "-c",
            script,
            import_mode,
            str(repo_root),
        ),
        cwd=tmp_path,
        env=_isolated_python_env(tmp_path / "subprocess-env"),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_chunking_pipeline_preserves_keyword_only_splitter_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pipeline must call compatible splitters through named parameters."""

    def keyword_only_splitter(
        text: str,
        *,
        chunk_size: int,
        chunk_overlap: int,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        assert chunk_size == 500
        assert chunk_overlap == 50
        return [{"content": text, "metadata": dict(base_metadata or {})}]

    monkeypatch.setattr(
        chunking_pipeline,
        "split_text_with_metadata",
        keyword_only_splitter,
    )
    pipeline = chunking_pipeline.ChunkingPipeline(
        enable_contextual=False,
        enable_guard=False,
    )

    chunks = pipeline.run("keyword-only", "material-1", {"title": "Paper"})

    assert len(chunks) == 1
    assert chunks[0].content == "keyword-only"
    assert chunks[0].title == "Paper"


@pytest.mark.parametrize(
    "loader",
    [load_hybrid_json, load_manifest_json, load_material_json],
)
def test_json_loaders_reject_non_object_payloads(
    tmp_path: Path,
    loader: Callable[[Path], dict[str, Any]],
) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        loader(payload_path)


@pytest.mark.parametrize("normalizer", [inspiration_ref_to_dict, rag_ref_to_dict])
def test_evidence_ref_normalizers_keep_dictionary_contract(
    normalizer: Callable[[object], dict[str, Any]],
) -> None:
    class InvalidDump:
        def model_dump(self) -> list[str]:
            return ["not", "a", "mapping"]

        def __str__(self) -> str:
            return "invalid-dump"

    assert normalizer(InvalidDump()) == {"raw": "invalid-dump"}


def test_wiki_evidence_reference_rejects_non_string_keys() -> None:
    with pytest.raises(TypeError, match="non-string key"):
        coerce_evidence_reference({1: "invalid"})


@pytest.mark.asyncio
async def test_duplicate_doi_rule_skips_missing_prepared_index() -> None:
    reports: list[dict[str, Any]] = []
    context = SimpleNamespace(
        item={"metadata": {"doi": "10.1000/example"}},
        options={},
        report=lambda **kwargs: reports.append(kwargs),
    )

    await NoDuplicateDoi().apply(context)

    assert reports == []


def test_cached_decorator_preserves_wrapped_function_metadata() -> None:
    cache = CacheManager()

    @cached(cache)
    def calculate(value: int) -> int:
        """Return the provided value."""

        return value

    assert calculate.__name__ == "calculate"
    assert calculate.__doc__ == "Return the provided value."
    assert calculate.__wrapped__(3) == 3


def test_mcp_accessor_ignores_invalid_internal_store_entries() -> None:
    store = SimpleNamespace(
        list_internal=lambda: [SimpleNamespace(server_slug="vision-auxiliary")]
    )

    assert _resolve_server("vision-auxiliary", store=store) is None


def test_mcp_accessor_accepts_canonical_store_model_identity(tmp_path: Path) -> None:
    store = CanonicalRuntimeMcpServerStore(tmp_path / "mcp-servers.json")
    created = store.create(
        CanonicalMcpServerConfigCreate(
            name="Vision Auxiliary",
            server_slug="vision-auxiliary",
            transport=CanonicalMcpTransport.STDIO,
            stdio=CanonicalMcpStdioConfig(
                command=sys.executable,
                args=["-c", "pass"],
            ),
            provenance=CanonicalMcpProvenance.RUNTIME_USER_CONFIRMED,
        )
    )
    store.update(
        created.server_id,
        CanonicalMcpServerConfigUpdate(
            approval_state=CanonicalMcpApprovalState.CATALOG_REVIEWED
        ),
    )
    store.update(
        created.server_id,
        CanonicalMcpServerConfigUpdate(
            approval_state=CanonicalMcpApprovalState.ENABLED_FOR_SESSION
        ),
    )

    resolved = get_enabled_server("vision-auxiliary", store=store)

    assert isinstance(resolved, CanonicalMcpServerConfig)


def test_recovery_console_forwards_required_fact_identity() -> None:
    calls: list[tuple[str, str, str]] = []
    fact_store = SimpleNamespace(
        get_fact_timeline=lambda namespace, subject, predicate: calls.append(
            (namespace, subject, predicate)
        )
        or []
    )
    console = RecoveryConsole(
        event_store=SimpleNamespace(),
        fact_store=fact_store,
    )

    assert console.get_fact_history("execution", "job-1", "status") == []
    assert calls == [("execution", "job-1", "status")]


def test_chat_bbox_coercion_preserves_json_list_contract() -> None:
    bbox = intelligent_chat_router._coerce_pdf_bbox_values([0.1, 0.2, 0.6, 0.3])

    assert isinstance(bbox, list)
    assert pdf_bbox_matches_unit(bbox, PdfBboxUnit.NORMALIZED_RATIO)


def test_chat_citation_scope_accepts_canonical_module_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Material:
        def to_dict(self) -> dict[str, object]:
            return {"material_id": "material-cited", "title": "Cited paper"}

    class Store:
        def list_materials(self, project_id: str) -> list[Material]:
            assert project_id == "project-1"
            return [Material()]

    canonical_resolution = CanonicalLocalCitationResolution(window=None)
    monkeypatch.setattr(
        intelligent_chat_router,
        "load_project_chunks_for_rag",
        lambda project_id: [] if project_id == "project-1" else None,
    )
    monkeypatch.setattr(
        intelligent_chat_router,
        "get_writing_resource_store",
        lambda: Store(),
    )
    monkeypatch.setattr(
        intelligent_chat_router,
        "resolve_local_citation_scope",
        lambda *_args, **_kwargs: canonical_resolution,
    )
    request = intelligent_chat_router.IntelligentChatRequest.model_validate(
        {
            "query": "Read the selected sentence",
            "project_id": "project-1",
            "material_id": "material-current",
            "current_pdf_context": {
                "material_id": "material-current",
                "selections": [
                    {"kind": "text", "page": 2, "text": "Selected sentence."}
                ],
            },
        }
    )

    resolutions = intelligent_chat_router._resolve_current_pdf_citation_scope(
        request,
        "project-1",
    )

    assert len(resolutions) == 1
    assert isinstance(resolutions[0], CanonicalLocalCitationResolution)
    assert resolutions[0] == canonical_resolution


def test_runtime_env_reads_the_feature_flag_module_used_by_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def disabled_wiki(name: str) -> bool:
        calls.append(name)
        return False

    monkeypatch.setattr(feature_flags, "is_enabled", disabled_wiki)

    assert wiki_enabled() is False
    assert calls == ["wiki"]


def test_default_memory_rule_conditions_return_real_booleans() -> None:
    engine = MemoryPolicyEngine()
    event = CanonicalEvent(
        event_id="event-1",
        correlation_id="correlation-1",
        timestamp="2026-07-26T00:00:00Z",
        event_type="error_occurred",
        error_code=None,
    )
    new_error_rule = next(rule for rule in engine._rules if rule.name == "new_error")

    result = new_error_rule.condition(event, None)

    assert result is False


def test_runtime_event_hook_emits_fact_compatible_iso_timestamp() -> None:
    event = RuntimeEventHook._create_job_started_event(
        {
            "job_id": "job-1",
            "session_id": "session-1",
            "user_id": "user-1",
        }
    )

    assert isinstance(event.timestamp, str)
    parsed = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None
    assert ExecutionFactRule().extract(event)[0].valid_from == parsed


def test_memory_fact_store_preserves_subsecond_job_transitions(tmp_path: Path) -> None:
    rule = ExecutionFactRule()
    started_event = CanonicalEvent(
        event_id="event-started",
        correlation_id="correlation-1",
        timestamp="2026-07-27T01:02:03.100000+00:00",
        job_id="job-1",
        aggregate_type="job",
        aggregate_id="job-1",
        event_type="job_started",
    )
    completed_event = CanonicalEvent(
        event_id="event-completed",
        correlation_id="correlation-1",
        timestamp="2026-07-27T01:02:03.900000+00:00",
        job_id="job-1",
        aggregate_type="job",
        aggregate_id="job-1",
        event_type="job_completed",
    )
    started_fact = rule.extract(started_event)[0]
    completed_fact = rule.extract(completed_event)[0]

    assert started_fact.fact_id != completed_fact.fact_id

    store = MemoryFactStore(str(tmp_path / "facts.db"))
    store.record_fact(started_fact)
    store.record_fact(completed_fact)

    timeline = store.get_fact_timeline("execution", "job-1", "status")
    assert [fact.object for fact in timeline] == ["running", "completed"]
    assert timeline[0].valid_to == completed_fact.valid_from
    current = store.get_current_facts("execution", "job-1", "status")
    assert len(current) == 1
    assert current[0].object == "completed"
    assert current[0].source_event_id == "event-completed"


def test_runtime_event_hook_normalizes_datetime_timestamp_to_iso_utc() -> None:
    event = RuntimeEventHook._create_job_started_event(
        {
            "job_id": "job-1",
            "session_id": "session-1",
            "user_id": "user-1",
            "timestamp": datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc),
        }
    )

    assert event.timestamp == "2026-07-27T01:00:00Z"


def test_discussion_context_maps_serialized_role_values() -> None:
    context = format_discussion_context(
        "topic",
        [{"role": "proponent", "content": "claim"}],
        current_role=AgentRole.MODERATOR,
    )

    assert "[支持方]: claim" in context


def _recovery_fact(
    fact_id: str,
    *,
    namespace: str = "execution",
    subject: str,
    predicate: str,
    value: str,
    valid_from: datetime,
) -> TemporalFact:
    return TemporalFact(
        fact_id=fact_id,
        namespace=namespace,
        subject=subject,
        predicate=predicate,
        object=value,
        object_type="string",
        valid_from=valid_from,
        valid_to=None,
        source_event_id=f"event-{fact_id}",
        created_at=valid_from,
    )


@pytest.fixture
def recovery_fact_history_console(tmp_path: Path) -> RecoveryConsole:
    store = MemoryFactStore(str(tmp_path / "recovery-facts.db"))
    start = datetime(2026, 7, 27, tzinfo=timezone.utc)
    facts = (
        _recovery_fact(
            "status-old",
            subject="job-1",
            predicate="status",
            value="running",
            valid_from=start,
        ),
        _recovery_fact(
            "status-new",
            subject="job-1",
            predicate="status",
            value="completed",
            valid_from=start + timedelta(seconds=1),
        ),
        _recovery_fact(
            "progress",
            subject="job-1",
            predicate="progress",
            value="100",
            valid_from=start + timedelta(seconds=2),
        ),
        _recovery_fact(
            "other-job",
            subject="job-2",
            predicate="status",
            value="queued",
            valid_from=start + timedelta(seconds=3),
        ),
        _recovery_fact(
            "other-namespace",
            namespace="skills",
            subject="job-1",
            predicate="status",
            value="ignored",
            valid_from=start + timedelta(seconds=4),
        ),
    )
    for fact in facts:
        store.record_fact(fact)
    return RecoveryConsole(event_store=SimpleNamespace(), fact_store=store)


def test_fact_history_one_argument_preserves_empty_timeline_result(
    recovery_fact_history_console: RecoveryConsole,
) -> None:
    facts = recovery_fact_history_console.get_fact_history("execution")

    assert facts == []


def test_fact_history_two_arguments_preserves_empty_timeline_result(
    recovery_fact_history_console: RecoveryConsole,
) -> None:
    facts = recovery_fact_history_console.get_fact_history("execution", "job-1")

    assert facts == []


def test_fact_history_three_arguments_uses_exact_timeline(
    recovery_fact_history_console: RecoveryConsole,
) -> None:
    facts = recovery_fact_history_console.get_fact_history(
        "execution",
        "job-1",
        "status",
    )

    assert [fact.fact_id for fact in facts] == ["status-old", "status-new"]


@pytest.mark.parametrize(
    "path",
    [
        "/recovery/autopilot/enable",
        "/recovery/autopilot/disable",
        "/recovery/autopilot/emergency-stop",
        "/recovery/autopilot/emergency-resume",
        "/recovery/autopilot/policy/set",
    ],
)
def test_autopilot_action_openapi_preserves_generic_response_schema(
    path: str,
) -> None:
    from recovery_autopilot_router import router

    app = FastAPI()
    app.include_router(router)
    document = app.openapi()
    response_schema = document["paths"][path]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert "$ref" not in response_schema
    assert response_schema["type"] == "object"
    assert response_schema["additionalProperties"] is True


class _FakeRecoverySpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.exceptions: list[BaseException] = []

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)


class _FakeRecoverySpanScope:
    def __init__(self, span: _FakeRecoverySpan) -> None:
        self.span = span
        self.exit_exception: BaseException | None = None

    def __enter__(self) -> _FakeRecoverySpan:
        return self.span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, tb
        self.exit_exception = exc


class _FakeRecoveryTracer:
    def __init__(self) -> None:
        self.span = _FakeRecoverySpan()
        self.scope = _FakeRecoverySpanScope(self.span)
        self.started_names: list[str] = []

    def start_as_current_span(self, name: str) -> _FakeRecoverySpanScope:
        self.started_names.append(name)
        return self.scope


class _FakeRecoveryTraceModule:
    def __init__(self, tracer: _FakeRecoveryTracer) -> None:
        self.tracer = tracer
        self.service_names: list[str] = []

    def get_tracer(self, service_name: str) -> _FakeRecoveryTracer:
        self.service_names.append(service_name)
        return self.tracer


def test_telemetry_accepts_valid_dynamic_trace_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _FakeRecoveryTracer()
    trace_module = _FakeRecoveryTraceModule(tracer)
    monkeypatch.setattr(recovery_telemetry, "otel_trace", trace_module)

    telemetry = recovery_telemetry.RecoveryTelemetry(
        service_name="recovery-test",
        metrics_collector=RecoveryMetricsCollector(),
    )
    with telemetry.start_span("recovery.normal", {"job_id": "job-1"}):
        pass

    assert trace_module.service_names == ["recovery-test"]
    assert tracer.started_names == ["recovery.normal"]
    assert tracer.span.attributes["job_id"] == "job-1"


def test_telemetry_rejects_trace_module_without_get_tracer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery_telemetry, "otel_trace", SimpleNamespace())

    with pytest.raises(AttributeError, match="get_tracer"):
        recovery_telemetry.RecoveryTelemetry()


def test_telemetry_rejects_non_callable_get_tracer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_telemetry,
        "otel_trace",
        SimpleNamespace(get_tracer="not-callable"),
    )

    with pytest.raises(TypeError, match="get_tracer"):
        recovery_telemetry.RecoveryTelemetry()


def test_telemetry_rejects_non_callable_start_as_current_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_module = SimpleNamespace(
        get_tracer=lambda service_name: SimpleNamespace(
            service_name=service_name,
            start_as_current_span="not-callable",
        )
    )
    monkeypatch.setattr(recovery_telemetry, "otel_trace", trace_module)

    with pytest.raises(TypeError, match="start_as_current_span"):
        recovery_telemetry.RecoveryTelemetry()


class _FakeRecoverySpanWithInvalidMethod:
    set_attribute = "not-callable"

    def record_exception(self, exc: BaseException) -> None:
        del exc


class _FakeInvalidRecoverySpanScope:
    def __enter__(self) -> _FakeRecoverySpanWithInvalidMethod:
        return _FakeRecoverySpanWithInvalidMethod()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb


class _FakeInvalidRecoverySpanTracer:
    def start_as_current_span(self, name: str) -> _FakeInvalidRecoverySpanScope:
        del name
        return _FakeInvalidRecoverySpanScope()


def test_telemetry_rejects_non_callable_span_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_module = SimpleNamespace(
        get_tracer=lambda service_name: _FakeInvalidRecoverySpanTracer()
    )
    monkeypatch.setattr(recovery_telemetry, "otel_trace", trace_module)
    telemetry = recovery_telemetry.RecoveryTelemetry()

    with pytest.raises(TypeError, match="set_attribute"):
        with telemetry.start_span("recovery.invalid-span"):
            pass


def test_telemetry_span_preserves_application_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _FakeRecoveryTracer()
    monkeypatch.setattr(
        recovery_telemetry,
        "otel_trace",
        _FakeRecoveryTraceModule(tracer),
    )
    telemetry = recovery_telemetry.RecoveryTelemetry(
        metrics_collector=RecoveryMetricsCollector(),
    )
    application_error = RuntimeError("application failure")

    with pytest.raises(RuntimeError) as raised:
        with telemetry.start_span("recovery.failure"):
            raise application_error

    assert raised.value is application_error
    assert tracer.span.exceptions == [application_error]
    assert tracer.scope.exit_exception is application_error


class _RecordingRecoveryEventStore:
    def __init__(self) -> None:
        self.events: list[CanonicalEvent] = []

    def append_event(self, event: CanonicalEvent) -> None:
        self.events.append(event)


def test_cli_enable_preserves_failure_when_enabled_state_has_no_policy(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    control_plane = AutopilotControlPlane(
        event_store=_RecordingRecoveryEventStore(),
        fact_store=SimpleNamespace(),
    )
    monkeypatch.setattr(
        recovery_autopilot_cli,
        "_control_plane_instance",
        control_plane,
    )
    operator_args = Namespace(operator_id="review-test", reason="state transition")
    assert recovery_autopilot_cli.cmd_autopilot_emergency_stop(operator_args) == 0
    assert recovery_autopilot_cli.cmd_autopilot_emergency_resume(operator_args) == 0
    assert control_plane.is_enabled()
    assert control_plane.get_current_policy() is None
    capsys.readouterr()

    result = recovery_autopilot_cli.cmd_autopilot_enable(
        Namespace(
            operator_id="review-test",
            policy="conservative",
            reason="must remain a failure",
        )
    )
    captured = capsys.readouterr()

    assert result == 1
    assert captured.out == ""
    assert captured.err == (
        "ERROR: Failed to enable autopilot: "
        "'NoneType' object has no attribute 'policy_name'\n"
    )
