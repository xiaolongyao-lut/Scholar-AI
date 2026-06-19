"""Stdio MCP acceptance for evidence-grounded academic writing workflows."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import socket
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "agent_mcp_server" / "bin" / "lit-assistant-mcp.ps1"
POWERSHELL_TIMEOUT_SEC = 12
MCP_INITIALIZE_TIMEOUT_SEC = 75.0
MCP_OPERATION_TIMEOUT_SEC = 30.0
_ISOLATED_ENV_KEYS = {
    "LITERATURE_ASSISTANT_BASE_URL",
    "LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT",
    "LITERATURE_ASSISTANT_USER_ROOT",
    "LITASSIST_API_CAPABILITY_AUTH",
    "LITASSIST_API_CAPABILITY_FILE",
    "LITASSIST_DESKTOP_RUNTIME_FILE",
}
_PROVIDER_ENV_PREFIXES = (
    "ANTHROPIC_",
    "ARK_",
    "DASHSCOPE_",
    "DEEPSEEK_",
    "EMBEDDING_",
    "GEMINI_",
    "GOOGLE_",
    "GROQ_",
    "JINA_",
    "MINIMAX_",
    "MISTRAL_",
    "MOONSHOT_",
    "OPENAI_",
    "OPENROUTER_",
    "PERPLEXITY_",
    "QWEN_",
    "RERANK_",
    "SILICONFLOW_",
    "VOLCANO_",
)
_PROVIDER_ENV_EXACT_KEYS = {
    "API_KEY",
    "BASE_URL",
    "CHAT_API_KEY",
    "CHAT_BASE_URL",
    "CHAT_MODEL",
    "MODEL",
}


def _unused_loopback_url() -> str:
    """Reserve-free loopback URL for an isolated backend process."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def _capability_file_for_url(runtime_root: Path, base_url: str) -> Path:
    """Return the wrapper's port-specific local API capability path."""

    parsed = urlparse(base_url)
    host = (parsed.hostname or "127.0.0.1").replace(":", "_").strip("_") or "loopback"
    port = parsed.port
    if port is None:
        raise ValueError("base_url must include a loopback port")
    return runtime_root / "api-capabilities" / f"{host}-{port}.json"


def _capability_headers(capability_file: Path) -> dict[str, str]:
    """Read capability headers without leaking token material to test output."""

    payload = json.loads(capability_file.read_text(encoding="utf-8"))
    header = payload.get("header")
    token = payload.get("token")
    if not isinstance(header, str) or not header.strip():
        raise AssertionError("capability file must contain a non-empty header")
    if not isinstance(token, str) or not token.strip():
        raise AssertionError("capability file must contain a non-empty token")
    return {header: token}


def _wait_for_capability_file(path: Path, timeout_sec: float = 30.0) -> dict[str, str]:
    """Wait until the backend writes the local API capability handoff file."""

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if path.is_file():
            return _capability_headers(path)
        time.sleep(0.1)
    raise AssertionError(f"capability file was not created: {path}")


def _stop_backend_on_port(port: int) -> None:
    """Stop the test uvicorn process listening on ``port`` on Windows."""

    if platform.system() != "Windows":
        return
    script = (
        "$connections = Get-NetTCPConnection -LocalPort "
        f"{port} -State Listen -ErrorAction SilentlyContinue; "
        "$connections | Select-Object -ExpandProperty OwningProcess -Unique | "
        "ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=POWERSHELL_TIMEOUT_SEC,
    )


def _start_backend_process(
    *,
    base_url: str,
    runtime_root: Path,
    user_root: Path,
    capability_file: Path,
    log_root: Path,
) -> subprocess.Popen[bytes]:
    """Start an isolated Uvicorn backend for stdio MCP acceptance tests."""

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if port is None:
        raise ValueError("base_url must include a loopback port")
    python_exe = REPO_ROOT / ".venv-1" / "Scripts" / "python.exe"
    if not python_exe.is_file():
        raise FileNotFoundError(f"Missing repository Python interpreter: {python_exe}")
    log_root.mkdir(parents=True, exist_ok=True)
    stdout_file = (log_root / "uvicorn.stdout.log").open("ab")
    stderr_file = (log_root / "uvicorn.stderr.log").open("ab")
    env = _isolated_process_env()
    env.update(
        {
            "LITERATURE_ASSISTANT_REPO_ROOT": str(REPO_ROOT),
            "LITERATURE_ASSISTANT_BASE_URL": base_url,
            "LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT": str(runtime_root),
            "LITERATURE_ASSISTANT_USER_ROOT": str(user_root),
            "LITASSIST_API_CAPABILITY_FILE": str(capability_file),
            "LITASSIST_API_CAPABILITY_AUTH": "1",
            "RUNTIME_ENV_DISABLE_DOTENV": "1",
            "LITASSIST_DISABLE_FILE_LOG": "1",
            "LITASSIST_DISABLE_ROUTE_DUMP": "1",
            "LITASSIST_CREDENTIAL_SECRET_BACKEND": "plaintext_file",
        }
    )
    return subprocess.Popen(
        [
            str(python_exe),
            "-m",
            "uvicorn",
            "literature_assistant.core.python_adapter_server:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=stdout_file,
        stderr=stderr_file,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if platform.system() == "Windows" else 0,
    )


def _isolated_process_env() -> dict[str, str]:
    """Return an environment without ambient pytest runtime attachment paths."""

    env = os.environ.copy()
    for key in (*_ISOLATED_ENV_KEYS, *_PROVIDER_ENV_EXACT_KEYS):
        env.pop(key, None)
    for key in tuple(env):
        if key.startswith(_PROVIDER_ENV_PREFIXES):
            env.pop(key, None)
    return env


def _wait_for_backend(base_url: str, capability_file: Path, timeout_sec: float = 60.0) -> dict[str, str]:
    """Wait for backend health and return the capability headers."""

    headers = _wait_for_capability_file(capability_file, timeout_sec=timeout_sec)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url.rstrip('/')}/health", headers=headers, timeout=2.0)
            response.raise_for_status()
            return headers
        except httpx.HTTPError:
            time.sleep(0.2)
    raise AssertionError(f"backend did not become healthy: {base_url}")


async def _wait_for_scan_job(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    job_id: str,
    *,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """Poll a runtime job until it reaches a terminal state."""

    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_id must be a non-empty string")
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        response = await client.get(f"/runtime/job/{job_id}/snapshot", headers=headers)
        response.raise_for_status()
        payload = response.json()
        status = str(payload.get("status", {}).get("status") or payload.get("job", {}).get("status") or "")
        if status in {"completed", "failed", "cancelled"}:
            return payload
        await asyncio.sleep(0.2)
    raise AssertionError(f"scan job did not finish within {timeout_sec} seconds: {job_id}")


async def _call_tool_ok(
    session: ClientSession,
    tool_name: str,
    args: dict[str, Any],
) -> Any:
    """Call an MCP tool and return its structured non-error payload."""

    result = await asyncio.wait_for(
        session.call_tool(tool_name, args),
        timeout=MCP_OPERATION_TIMEOUT_SEC,
    )
    structured = result.structuredContent
    if not isinstance(structured, dict):
        raise AssertionError(f"{tool_name} returned no structured content: {result.content!r}")
    if structured.get("is_error") is True:
        raise AssertionError(f"{tool_name} returned error: {structured.get('error_code')}")
    return structured.get("data")


def _draft_review_and_introduction(
    outline_items: list[dict[str, Any]],
    evidence_pack_ref: str,
    refs: list[dict[str, Any]],
) -> str:
    """Simulate an external MCP agent drafting only from returned refs."""

    if not outline_items:
        raise ValueError("outline_items must be non-empty")
    if not evidence_pack_ref.startswith("evidence_pack:"):
        raise ValueError("evidence_pack_ref must identify an evidence pack")
    if len(refs) < 2:
        raise ValueError("at least two evidence refs are required")
    ref_ids = [str(ref["ref_id"]) for ref in refs[:2]]
    summaries = [str(ref["summary"]) for ref in refs[:2]]
    return (
        "# 综述\n"
        f"证据包 {evidence_pack_ref} 表明，增材制造 AlSi10Mg 合金中的孔隙缺陷、熔池稳定性与疲劳裂纹萌生"
        f"需要被放在同一证据链中讨论[{ref_ids[0]}]。"
        "现有材料支持区分 lack-of-fusion 与 keyhole 两类缺陷，并将其与热输入、激光振荡和近表面失效联系起来。"
        f"{outline_items[0]['title']} 应首先限定材料体系、工艺窗口与证据适用边界。\n\n"
        "# 引言\n"
        "随着 LPBF AlSi10Mg 用于轻量化承载结构，孔隙调控已经从单一成形质量问题转化为可靠性评价问题。"
        f"{summaries[0]} 强调近表面缺陷对疲劳裂纹萌生的控制作用，"
        f"{summaries[1]} 则说明振荡激光可通过改变熔池流动降低孔隙率[{ref_ids[1]}]。"
        "因此，本文围绕缺陷形成、工艺调控和性能响应建立综述框架，并在每一节保留可回读的证据锚点。"
    )


def _markdown_to_html(text: str) -> str:
    """Convert a deterministic two-section Markdown draft into simple HTML."""

    blocks: list[str] = []
    for paragraph in text.split("\n\n"):
        cleaned = paragraph.strip()
        if not cleaned:
            continue
        if cleaned.startswith("# "):
            blocks.append(f"<h1>{cleaned[2:].strip()}</h1>")
        else:
            blocks.append(f"<p>{cleaned}</p>")
    return "".join(blocks)


def _academic_reference_html(draft: str) -> str:
    """Return scholarly HTML containing citation, caption, table, and formula targets."""

    if not isinstance(draft, str) or not draft.strip():
        raise ValueError("draft must be a non-empty string")
    return (
        _markdown_to_html(draft)
        + "<p>如图 1、表 1 和式（1）所示，熔池扰动、孔隙形貌与力学响应之间存在可追溯的证据链。</p>"
        + "<figcaption>图 1 熔池扰动与孔隙演化示意图</figcaption>"
        + "<table>"
        + "<tr><th>参数</th><th>趋势</th></tr>"
        + "<tr><td>扫描速度</td><td>孔隙率变化</td></tr>"
        + "</table>"
        + "<figcaption>表 1 AlSi10Mg 工艺参数对比</figcaption>"
        + "<p>式（1）：<span data-formula=\"P = F / A\" data-equation-number=\"1\"></span></p>"
    )


def _document_xml_from_docx(path: Path) -> str:
    """Extract the main WordprocessingML document from an exported DOCX path."""

    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path")
    if path.suffix.lower() != ".docx":
        raise ValueError("path must point to a .docx file")
    if not path.is_file():
        raise FileNotFoundError(path)
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def _assert_academic_quality(text: str) -> None:
    """Assert structure, evidence grounding, and non-chat academic tone."""

    assert len(text) >= 260
    assert "# 综述" in text
    assert "# 引言" in text
    assert "evidence_pack:" in text
    assert re.search(r"\[chunk:[^\]]+\]", text), "chunk-ref citations are required"
    assert any(term in text for term in ("因此", "表明", "支持", "影响", "关键"))
    assert all(term not in text for term in ("我将", "下面我", "作为AI", "首先我会", "本文档将"))
    assert "证据锚点" in text


def _agent_resource_refs(refs: list[dict[str, Any]], *, maximum: int = 2) -> list[dict[str, Any]]:
    """Normalize evidence refs into the agent-bridge resource-ref shape."""

    normalized: list[dict[str, Any]] = []
    for ref in refs[:maximum]:
        ref_id = str(ref.get("ref_id") or "").strip()
        if not ref_id:
            raise ValueError("evidence ref must include ref_id")
        normalized.append(
            {
                "ref_id": ref_id,
                "kind": "chunk",
                "summary": str(ref.get("summary") or "")[:500],
                "read_endpoint": str(ref.get("read_endpoint") or ""),
            }
        )
    return normalized


def test_stdio_mcp_agent_can_generate_academic_review_chain(tmp_path: Path) -> None:
    """External stdio MCP clients can drive the scholarly writing tool chain."""

    if platform.system() != "Windows":
        return

    base_url = _unused_loopback_url()
    parsed_port = urlparse(base_url).port
    if parsed_port is None:
        raise AssertionError("test backend URL must include a port")

    source_root = tmp_path / "AlSi10Mg_sources"
    source_root.mkdir()
    (source_root / "lpbf-defect-control.md").write_text(
        (
            "# Selective laser melting defect control in AlSi10Mg\n\n"
            "Selective laser melting of AlSi10Mg creates lack-of-fusion pores and keyhole pores. "
            "Fatigue cracks preferentially initiate at near-surface defects, and process-window control "
            "links heat input, porosity, and crack-initiation behavior."
        ),
        encoding="utf-8",
    )
    (source_root / "laser-oscillation-porosity.md").write_text(
        (
            "# Oscillating laser welding porosity suppression\n\n"
            "Oscillating laser strategies redistribute molten-pool flow and can reduce porosity in "
            "AlSi10Mg processing, but the process window remains coupled with heat input, microstructure, "
            "and fatigue reliability."
        ),
        encoding="utf-8",
    )

    runtime_root = tmp_path / "runtime_state"
    user_root = tmp_path / "user_root"
    capability_file = _capability_file_for_url(runtime_root, base_url)
    backend_process = _start_backend_process(
        base_url=base_url,
        runtime_root=runtime_root,
        user_root=user_root,
        capability_file=capability_file,
        log_root=tmp_path / "backend_logs",
    )

    async def run_acceptance() -> None:
        headers = _wait_for_backend(base_url, capability_file)
        env = _isolated_process_env()
        env.update(
            {
                "LITERATURE_ASSISTANT_REPO_ROOT": str(REPO_ROOT),
                "LITERATURE_ASSISTANT_BASE_URL": base_url,
                "LITASSIST_MCP_SKIP_BACKEND_AUTOSTART": "1",
                "LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT": str(runtime_root),
                "LITERATURE_ASSISTANT_USER_ROOT": str(user_root),
                "LITASSIST_API_CAPABILITY_FILE": str(capability_file),
                "LITASSIST_API_CAPABILITY_AUTH": "1",
                "RUNTIME_ENV_DISABLE_DOTENV": "1",
                "LITASSIST_DISABLE_FILE_LOG": "1",
                "LITASSIST_DISABLE_ROUTE_DUMP": "1",
                "LITASSIST_CREDENTIAL_SECRET_BACKEND": "plaintext_file",
            }
        )
        server_params = StdioServerParameters(
            command="powershell",
            args=[
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(WRAPPER),
            ],
            cwd=REPO_ROOT,
            env=env,
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await asyncio.wait_for(
                    session.initialize(),
                    timeout=MCP_INITIALIZE_TIMEOUT_SEC,
                )
                assert initialized.serverInfo.name == "literature-assistant"
                tool_listing = await asyncio.wait_for(session.list_tools(), timeout=MCP_OPERATION_TIMEOUT_SEC)
                tool_names = {tool.name for tool in tool_listing.tools}
                assert "literature.project_scan_folder" in tool_names
                assert "literature.search_refs" in tool_names
                assert "literature.search_literature" not in tool_names
                assert "literature.ingest_then_search" not in tool_names

                async with httpx.AsyncClient(base_url=base_url, timeout=20.0) as backend:
                    created_project = await backend.post(
                        "/resources/project",
                        headers=headers,
                        json={
                            "title": "Stdio MCP AlSi10Mg Academic Writing",
                            "description": "External MCP acceptance fixture",
                            "content_type": "academic",
                            "user_id": "stdio-mcp-test",
                        },
                    )
                    created_project.raise_for_status()
                    project_id = created_project.json()["project_id"]

                    bound = await backend.put(
                        f"/resources/project/{project_id}/source-folder",
                        headers=headers,
                        params={"source_folder": str(source_root)},
                    )
                    bound.raise_for_status()
                    binding = bound.json().get("source_folder_ref")
                    assert isinstance(binding, dict)
                    assert binding.get("display_name") == source_root.name
                    assert "path" not in binding

                    scan = await _call_tool_ok(
                        session,
                        "literature.project_scan_folder",
                        {
                            "project_id": project_id,
                            "scan_mode": "fast",
                            "batch_size": 2,
                            "max_workers": 2,
                        },
                    )
                    runtime_job_ref = scan.get("runtime_job_ref")
                    assert isinstance(runtime_job_ref, dict)
                    assert runtime_job_ref.get("kind") == "resource_ingest"
                    scan_snapshot = await _wait_for_scan_job(backend, headers, str(runtime_job_ref.get("job_id")))
                    assert scan_snapshot["status"]["status"] == "completed"

                    materials_data = await _call_tool_ok(
                        session,
                        "literature.list_materials",
                        {"project_id": project_id},
                    )
                    materials = materials_data if isinstance(materials_data, list) else materials_data.get("items")
                    if not isinstance(materials, list):
                        materials_response = await backend.get("/resources/materials", headers=headers, params={"project_id": project_id})
                        materials_response.raise_for_status()
                        materials = materials_response.json()
                    assert len(materials) == 2
                    material_ids = [str(material["material_id"]) for material in materials]

                refs = await _call_tool_ok(
                    session,
                    "literature.search_refs",
                    {
                        "project_id": project_id,
                        "query": "AlSi10Mg porosity fatigue laser oscillation",
                        "top_k": 5,
                    },
                )
                assert refs["refs"]
                assert "content" not in str(refs["refs"][0])
                assert "read_endpoint" in refs["refs"][0]

                evidence_pack = await _call_tool_ok(
                    session,
                    "literature.evidence_pack_build",
                    {
                        "project_id": project_id,
                        "query": "AlSi10Mg porosity fatigue laser oscillation",
                        "section_id": "review-introduction",
                        "top_k": 5,
                    },
                )
                assert evidence_pack["evidence_pack_ref"].startswith("evidence_pack:")
                assert evidence_pack["retrieval_method"] == "lexical"
                assert evidence_pack["rerank_status"] == "unavailable"
                assert len(evidence_pack["evidence_refs"]) >= 2
                assert "content" not in str(evidence_pack["evidence_refs"][0])

                resource = await _call_tool_ok(
                    session,
                    "literature.agent_resource_read",
                    {
                        "ref_id": evidence_pack["evidence_refs"][0]["ref_id"],
                        "project_id": project_id,
                        "max_chars": 900,
                    },
                )
                assert "fatigue" in str(resource).lower() or "porosity" in str(resource).lower()

                outline = await _call_tool_ok(
                    session,
                    "literature.outline_generate",
                    {
                        "project_id": project_id,
                        "topic": "AlSi10Mg 增材制造孔隙调控与疲劳性能综述",
                        "content_type": "academic",
                        "target_length": 6000,
                        "focus_areas": ["孔隙形成机制", "振荡激光调控", "疲劳裂纹萌生"],
                        "existing_materials": material_ids,
                    },
                )
                assert outline["items"]
                assert all(str(item.get("description") or "").strip() for item in outline["items"])

                draft = _draft_review_and_introduction(
                    outline["items"],
                    evidence_pack["evidence_pack_ref"],
                    evidence_pack["evidence_refs"],
                )
                _assert_academic_quality(draft)

                journal_draft = await _call_tool_ok(
                    session,
                    "literature.journal_style_spec_draft",
                    {
                        "project_id": project_id,
                        "journal_name": "Journal of Additive Manufacturing Letters",
                        "spec_text": (
                            "Use APA author-year citations, Times New Roman 12 pt body text, "
                            "2.54 cm margins on all sides, figure captions below figures, and table captions above tables."
                        ),
                    },
                )
                assert journal_draft["requires_confirmation"] is True
                assert journal_draft["profile"]["citation_style"] == "author_year"

                confirmed = await _call_tool_ok(
                    session,
                    "literature.journal_style_spec_confirm",
                    {
                        "project_id": project_id,
                        "draft_id": journal_draft["draft_id"],
                        "confirmed_by": "stdio-mcp-test",
                    },
                )
                profile_id = confirmed["profile"]["profile_id"]
                assert str(profile_id).startswith("custom_")

                exported = await _call_tool_ok(
                    session,
                    "literature.export_docx",
                    {
                        "html": _academic_reference_html(draft),
                        "title": "AlSi10Mg MCP Review Introduction",
                        "style_profile": profile_id,
                        "project_id": project_id,
                        "verify_with_word": True,
                    },
                )
                assert exported["bytes"] > 1000
                assert Path(exported["artifact_path"]).is_file()
                assert str(exported["artifact_path"]).endswith(".docx")
                assert f"style_profile={profile_id}" in exported["quality"]
                assert "citation_style=author_year" in exported["quality"]
                assert "tables=1" in exported["quality"]
                assert "captions=2" in exported["quality"]
                assert "crossrefs=3" in exported["quality"]
                assert "formulas=1" in exported["quality"]
                document_xml = _document_xml_from_docx(Path(exported["artifact_path"]))
                assert "REF litassist_figure_1" in document_xml
                assert "REF litassist_table_1" in document_xml
                assert "REF litassist_equation_1" in document_xml
                assert "w:bookmarkStart" in document_xml
                assert "w:name=\"litassist_figure_1\"" in document_xml
                assert "w:name=\"litassist_table_1\"" in document_xml
                assert "w:name=\"litassist_equation_1\"" in document_xml
                assert "m:oMath" in document_xml
                assert "P = F / A" in document_xml

                agent_request = await _call_tool_ok(
                    session,
                    "literature.agent_request_create",
                    {
                        "intent": "draft_review_introduction",
                        "user_text": "Write a review and introduction from MCP evidence refs.",
                        "project_id": project_id,
                        "resource_refs": _agent_resource_refs(evidence_pack["evidence_refs"]),
                        "agent_host": "stdio-mcp-test",
                        "source": "mcp",
                        "wiki_candidate": True,
                        "graph_candidate": True,
                    },
                )
                request_id = str(agent_request["request_id"])
                progress = await _call_tool_ok(
                    session,
                    "literature.agent_progress",
                    {
                        "request_id": request_id,
                        "stage": "draft",
                        "message": "Drafted review/introduction from MCP evidence refs",
                        "progress": 70,
                        "data": {"evidence_ref_count": len(evidence_pack["evidence_refs"])},
                    },
                )
                assert isinstance(progress, dict)
                result = await _call_tool_ok(
                    session,
                    "literature.agent_result",
                    {
                        "request_id": request_id,
                        "text": draft,
                        "evidence_refs": _agent_resource_refs(evidence_pack["evidence_refs"]),
                        "metadata": {
                            "generated_via": "stdio_mcp",
                            "artifact_path": exported["artifact_path"],
                        },
                    },
                )
                assert result["request_id"] == request_id
                assert result["job"]["status"] == "completed"
                assert result["artifacts"]

    try:
        asyncio.run(run_acceptance())
    finally:
        backend_process.terminate()
        try:
            backend_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            backend_process.kill()
            backend_process.wait(timeout=10)
        _stop_backend_on_port(parsed_port)
