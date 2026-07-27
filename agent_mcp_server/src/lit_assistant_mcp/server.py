"""FastMCP stdio server for the Literature Assistant local toolbox."""

import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from .audit import AuditLog
from .repo_root import is_repo_root
from .tools import (
    ExperimentalTools,
    RuntimeTools,
    SourceTools,
    WorkflowTools,
    create_default_experimental_tools,
    create_default_runtime_tools,
    create_default_source_tools,
    create_default_workflow_tools,
)
from .workflow_runtime.interpreter import ToolCallable

SIDEBAR_APP_RESOURCE_URI = "ui://scholar-ai/sidebar"
SIDEBAR_APP_RESOURCE_MIME_TYPE = "text/html;profile=mcp-app"
SIDEBAR_APP_STATUS_TOOL_NAME = "literature.sidebar_app_status"
NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI = "ui://scholar-ai/native-handoff-probe"
NATIVE_HANDOFF_WIDGET_TOOL_NAME = "literature.codex_handoff_widget"
NATIVE_HANDOFF_WIDGET_PROBE_TOOL_NAME = "literature.native_handoff_widget_probe"
NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION = "scholar-ai-native-handoff-widget-probe/v1"
MCP_TOOL_PROFILE_ENV = "LITASSIST_MCP_TOOL_PROFILE"
EXPERIMENTAL_TOOLS_ENV = "LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS"
MCP_TOOL_PROFILE_FULL = "full"
MCP_TOOL_PROFILE_MINIMAL = "minimal"
SUPPORTED_MCP_TOOL_PROFILES = frozenset({MCP_TOOL_PROFILE_FULL, MCP_TOOL_PROFILE_MINIMAL})
MINIMAL_MCP_TOOL_NAMES = frozenset(
    {
        "source.search",
        "source.read_file",
        "source.read_symbols",
        "source.inspect_routes",
        "source.find_references",
        "literature.config_status",
        "literature.health_check",
        "literature.list_projects",
        "literature.list_materials",
        "literature.read_material",
        "literature.launch_desktop",
        "literature.search_refs",
        "literature.evidence_pack_build",
        "literature.evidence_integrity_gate",
        "literature.get_material_chunks",
        "literature.agent_resource_read",
        "literature.agent_request_create",
        "literature.agent_result",
        "literature.answer_receipt_read",
        "literature.answer_receipt_list",
        "literature.export_docx",
        "literature.export_annotations_markdown",
    }
)
EXPERIMENTAL_MCP_TOOL_NAMES = frozenset(
    {
        "literature.ocr_status",
        "literature.ocr_engines",
        "literature.ocr_health",
        "literature.ocr_execution_probe",
        "literature.ocr_material",
        "literature.prepare_visual_review",
        "literature.translate_pack",
        "literature.export_project_pack",
        "workflow.run_python_sandbox",
    }
)
SIDEBAR_APP_TOOL_META: dict[str, Any] = {
    "ui": {
        "resourceUri": SIDEBAR_APP_RESOURCE_URI,
        "visibility": ["model", "app"],
    },
}
NATIVE_HANDOFF_WIDGET_TOOL_META: dict[str, Any] = {
    "ui": {
        "resourceUri": NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
        "visibility": ["model", "app"],
    },
    "ui/resourceUri": NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
    "openai/outputTemplate": NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
    "openai/widgetAccessible": True,
    "openai/toolInvocation/invoking": "正在打开 Scholar AI 主栏交接...",
    "openai/toolInvocation/invoked": "Scholar AI 主栏交接已准备",
}
NATIVE_HANDOFF_WIDGET_PROBE_TOOL_META: dict[str, Any] = dict(NATIVE_HANDOFF_WIDGET_TOOL_META)


def _bounded_widget_text(value: str | None, *, limit: int = 160) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    if not normalized:
        return None
    return normalized[:limit]


def _native_handoff_widget_probe_html() -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scholar AI 主栏交接</title>
  <style>
    :root {{
      color-scheme: light dark;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #647084;
      --line: #d8dfeb;
      --accent: #176b58;
      --accent-ink: #ffffff;
      --soft: #eef6f2;
      --soft-ink: #176b58;
      --warn: #8a5a0a;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --panel: #181f2a;
        --ink: #eef3fb;
        --muted: #aeb8c9;
        --line: #303b4c;
        --accent: #53b99f;
        --accent-ink: #071310;
        --soft: #18352f;
        --soft-ink: #8be1ca;
        --warn: #e1b464;
      }}
    }}
    * {{ box-sizing: border-box; }}
    html {{ background: transparent; }}
    body {{
      margin: 0;
      background: transparent;
      color: var(--ink);
      font: 13px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      min-width: 260px;
      max-width: 520px;
      padding: 10px;
      display: grid;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      display: grid;
      gap: 8px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }}
    .title-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-width: 0;
    }}
    h1 {{
      font-size: 14px;
      line-height: 1.25;
      margin: 0;
      letter-spacing: 0;
    }}
    p {{ margin: 0; }}
    .muted {{ color: var(--muted); }}
    .microcopy {{
      color: var(--muted);
      font-size: 12px;
    }}
    .status {{
      color: var(--warn);
      min-height: 18px;
      font-size: 12px;
    }}
    .status[data-tone="ready"],
    .status[data-tone="sent"] {{
      color: var(--soft-ink);
    }}
    .sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .pill {{
      border-radius: 999px;
      background: var(--soft);
      color: var(--soft-ink);
      flex: 0 0 auto;
      font-size: 11px;
      line-height: 1;
      padding: 5px 7px;
      white-space: nowrap;
    }}
    button {{
      width: 100%;
      border: 0;
      border-radius: 7px;
      background: var(--accent);
      color: var(--accent-ink);
      cursor: pointer;
      font: inherit;
      font-weight: 650;
      min-height: 42px;
      padding: 9px 10px;
    }}
    button:disabled {{
      cursor: default;
      opacity: 0.55;
    }}
    code, .debug {{
      overflow-wrap: anywhere;
      color: var(--muted);
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }}
  </style>
</head>
<body>
  <main data-schema-version="{NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION}">
    <section aria-label="Scholar AI native handoff">
      <div class="title-row">
        <h1>交接到 Codex 主栏</h1>
        <span id="connection-pill" class="pill">连接中</span>
      </div>
      <p id="handoff-copy" class="microcopy">点击后把当前 Scholar AI 任务发送到主栏。</p>
      <button id="send-probe" type="button" disabled>发送到主栏</button>
      <p id="status" class="status" role="status">正在连接宿主...</p>
      <p id="probe-meta" class="sr-only">request_id: 等待宿主数据</p>
      <code id="payload" hidden>等待发送</code>
    </section>
  </main>
  <script>
    (() => {{
      "use strict";

      const PROTOCOL_VERSION = "2026-01-26";
      const button = document.getElementById("send-probe");
      const statusEl = document.getElementById("status");
      const connectionPill = document.getElementById("connection-pill");
      const probeMetaEl = document.getElementById("probe-meta");
      const payloadEl = document.getElementById("payload");
      const handoffCopyEl = document.getElementById("handoff-copy");
      const pending = new Map();
      const state = {{ ready: false, widgetData: {{}}, bridge: "raw-ui-message", hostCapabilities: {{}} }};
      let nextId = 1;

      function setStatus(text, tone) {{
        statusEl.textContent = text;
        statusEl.dataset.tone = tone || "neutral";
      }}

      function setConnection(text, tone) {{
        connectionPill.textContent = text;
        connectionPill.dataset.tone = tone || "neutral";
      }}

      function hasRealRequest() {{
        const requestId = String(state.widgetData.request_id || "").trim();
        return requestId && requestId !== "s74_probe";
      }}

      function updateWidgetCopy() {{
        if (hasRealRequest()) {{
          button.textContent = "发送到主栏";
          handoffCopyEl.textContent = "点击后把接手指令发送到当前 Codex 主栏。";
          return;
        }}
        button.textContent = "发送测试消息";
          handoffCopyEl.textContent = "发送一条测试消息，确认宿主消息桥可用。";
      }}

      function updateProbeMeta() {{
        const requestId = state.widgetData.request_id || "s74_probe";
        const projectId = state.widgetData.project_id || "未指定";
        const receiptId = state.widgetData.receipt_id || "未指定";
        const refCount = state.widgetData.ref_count ?? "未指定";
        probeMetaEl.textContent = `request_id: ${{requestId}} · project_id: ${{projectId}} · receipt: ${{receiptId}} · refs: ${{refCount}}`;
        updateWidgetCopy();
      }}

      function applyHostContext(context) {{
        if (!context) return;
        if (context.theme === "dark" || context.theme === "light") {{
          document.documentElement.dataset.theme = context.theme;
          document.documentElement.style.colorScheme = context.theme;
        }}
        if (context.styles && context.styles.variables) {{
          for (const [name, value] of Object.entries(context.styles.variables)) {{
            if (typeof name === "string" && typeof value === "string") {{
              document.documentElement.style.setProperty(name, value);
            }}
          }}
        }}
      }}

      function withTimeout(promise, ms, label) {{
        let timer;
        const timeout = new Promise((_, reject) => {{
          timer = window.setTimeout(() => reject(new Error(label)), ms);
        }});
        return Promise.race([promise, timeout]).finally(() => window.clearTimeout(timer));
      }}

      function canUseOpenAIBridge() {{
        const api = window.openai;
        return Boolean(
          api &&
          (
            typeof api.sendFollowUpMessage === "function" ||
            typeof api.sendMessage === "function"
          )
        );
      }}

      function openAIToolPayload() {{
        const api = window.openai;
        if (!api || typeof api !== "object") return {{}};
        const rawToolResult = api.rawToolResult && typeof api.rawToolResult === "object"
          ? toolResultPayload(api.rawToolResult)
          : {{}};
        const toolOutput = api.toolOutput && typeof api.toolOutput === "object"
          ? api.toolOutput
          : {{}};
        const responseMeta = api.toolResponseMetadata && typeof api.toolResponseMetadata === "object"
          ? api.toolResponseMetadata
          : {{}};
        const directWidgetData = api.widgetData && typeof api.widgetData === "object"
          ? api.widgetData
          : {{}};
        return Object.assign({{}}, rawToolResult, toolOutput, responseMeta.widgetData || {{}}, directWidgetData);
      }}

      function applyOpenAIState() {{
        const api = window.openai;
        if (!api || typeof api !== "object") return false;
        applyHostContext(api.hostContext);
        const payload = openAIToolPayload();
        if (Object.keys(payload).length > 0) {{
          state.widgetData = Object.assign({{}}, state.widgetData, payload);
          updateProbeMeta();
        }}
        return canUseOpenAIBridge();
      }}

      function markReady(bridgeName, statusText) {{
        state.ready = true;
        state.bridge = bridgeName;
        updateProbeMeta();
        button.disabled = false;
        setConnection("已连接", "ready");
        updateWidgetCopy();
        setStatus(statusText, "ready");
      }}

      function request(method, params, timeoutMs) {{
        const id = `scholar_ai_probe_${{nextId++}}`;
        const message = {{ jsonrpc: "2.0", id, method, params }};
        return new Promise((resolve, reject) => {{
          const timer = window.setTimeout(() => {{
            pending.delete(id);
            reject(new Error(`${{method}} timed out`));
          }}, timeoutMs || 8000);
          pending.set(id, {{ resolve, reject, timer }});
          window.parent.postMessage(message, "*");
        }});
      }}

      function notify(method, params) {{
        window.parent.postMessage({{ jsonrpc: "2.0", method, params: params || {{}} }}, "*");
      }}

      function promptFromMessage(message) {{
        if (typeof message === "string") return message;
        if (message && typeof message.prompt === "string") return message.prompt;
        if (message && typeof message.content === "string") return message.content;
        return "";
      }}

      function contentFromMessage(message, prompt) {{
        if (message && Array.isArray(message.content)) return message.content;
        return [{{ type: "text", text: prompt }}];
      }}

      function publishHostGlobals(globals) {{
        const openaiGlobals = Object.assign({{}}, globals);
        const existingOpenAI = window.openai && typeof window.openai === "object" ? window.openai : {{}};
        if (typeof existingOpenAI.sendFollowUpMessage === "function") {{
          delete openaiGlobals.sendFollowUpMessage;
        }}
        if (typeof existingOpenAI.sendMessage === "function") {{
          delete openaiGlobals.sendMessage;
        }}
        window.scholarAiMcp = Object.assign(window.scholarAiMcp || {{}}, globals);
        window.openai = Object.assign(existingOpenAI, openaiGlobals);
        window.dispatchEvent(new CustomEvent("openai:set_globals", {{
          detail: {{ globals: window.openai }}
        }}));
      }}

      function hostSupportsMessage(hostCapabilities) {{
        return Boolean(hostCapabilities && typeof hostCapabilities === "object" && hostCapabilities.message);
      }}

      function installHostMessageBridge(initializeResult) {{
        const hostCapabilities = initializeResult && typeof initializeResult.hostCapabilities === "object"
          ? initializeResult.hostCapabilities
          : {{}};
        const hostInfo = initializeResult && typeof initializeResult.hostInfo === "object"
          ? initializeResult.hostInfo
          : {{}};
        state.hostCapabilities = hostCapabilities;
        publishHostGlobals({{
          hostCapabilities,
          hostInfo,
          sendMessage: async (message) => {{
            const prompt = promptFromMessage(message);
            const content = contentFromMessage(message, prompt);
            if (!prompt && content.length === 0) throw new Error("Missing message content.");
            return await request("ui/message", {{
              role: "user",
              content
            }}, 8000);
          }},
          sendFollowUpMessage: async (message) => {{
            const prompt = promptFromMessage(message);
            if (!prompt) throw new Error("Missing follow-up prompt.");
            return await request("ui/message", {{
              role: "user",
              content: contentFromMessage(message, prompt)
            }}, 8000);
          }},
          notifyResize: () => notify("ui/notifications/size-changed", currentSize())
        }});
      }}

      function currentSize() {{
        return {{
          width: Math.ceil(window.innerWidth || document.documentElement.clientWidth || 320),
          height: Math.ceil(document.documentElement.scrollHeight || 160)
        }};
      }}

      function toolResultPayload(result) {{
        if (!result || typeof result !== "object") return {{}};
        const meta = result._meta && typeof result._meta === "object" ? result._meta : {{}};
        const structured = result.structuredContent && typeof result.structuredContent === "object"
          ? result.structuredContent
          : {{}};
        const structuredMeta = structured._meta && typeof structured._meta === "object"
          ? structured._meta
          : {{}};
        const nestedWidgetData = structured.widget_data && typeof structured.widget_data === "object"
          ? structured.widget_data
          : {{}};
        return Object.assign(
          {{}},
          structured,
          nestedWidgetData,
          structuredMeta.widgetData || {{}},
          meta.widgetData || {{}}
        );
      }}

      function receive(event) {{
        if (event.source !== window.parent) return;
        const data = event.data;
        if (!data || typeof data !== "object") return;

        if (Object.prototype.hasOwnProperty.call(data, "id")) {{
          const id = String(data.id);
          const entry = pending.get(id);
          if (entry) {{
            pending.delete(id);
            window.clearTimeout(entry.timer);
            if (data.error) {{
              entry.reject(new Error(data.error.message || "Host rejected request."));
            }} else {{
              entry.resolve(data.result || {{}});
            }}
          }}
          return;
        }}

        if (data.method === "ui/notifications/host-context-changed") {{
          applyHostContext(data.params);
          return;
        }}
        if (data.method === "ui/notifications/tool-result") {{
          const result = data.params && data.params.result ? data.params.result : data.params;
          state.widgetData = toolResultPayload(result);
          updateProbeMeta();
        }}
      }}

      function handoffMessage() {{
        const requestId = state.widgetData.request_id || "s74_probe";
        const projectId = state.widgetData.project_id || "未指定";
        const note = state.widgetData.note || "";
        if (hasRealRequest()) {{
          return [
            `请接手 Scholar AI 交接任务 ${{requestId}}：`,
            "用 literature.agent_request_read 读取限定证据，基于 evidence refs 回答，并用 literature.agent_result 写回同一 request_id。"
          ].join("");
        }}
        return [
          "Scholar AI native handoff widget test",
          "",
          `request_id: ${{requestId}}`,
          `project_id: ${{projectId}}`,
          note || "请回复 S74_NATIVE_HANDOFF_WIDGET_PROBE_RECEIVED。"
        ].join("\\n");
      }}

      async function sendToHost(text) {{
        const content = [{{ type: "text", text }}];
        const api = window.openai;
        if (api && typeof api.sendFollowUpMessage === "function") {{
          state.bridge = "openai.sendFollowUpMessage";
          return await withTimeout(
            Promise.resolve(api.sendFollowUpMessage({{ prompt: text, content }})),
            8000,
            "Host did not accept the follow-up message."
          );
        }}
        if (api && typeof api.sendMessage === "function") {{
          state.bridge = "openai.sendMessage";
          return await withTimeout(
            Promise.resolve(api.sendMessage({{ role: "user", content }})),
            8000,
            "Host did not accept the message."
          );
        }}
        const scholarApi = window.scholarAiMcp;
        if (scholarApi && typeof scholarApi.sendFollowUpMessage === "function") {{
          state.bridge = "scholarAiMcp.sendFollowUpMessage";
          return await withTimeout(
            Promise.resolve(scholarApi.sendFollowUpMessage({{ prompt: text, content }})),
            8000,
            "Host did not accept the follow-up message."
          );
        }}
        state.bridge = "ui/message";
        return await request("ui/message", {{
          role: "user",
          content
        }}, 8000);
      }}

      async function initialize() {{
        window.addEventListener("message", receive);
        window.addEventListener("openai:set_globals", () => {{
          if (applyOpenAIState() && !state.ready) {{
            markReady("openai", "宿主消息桥可用。");
          }}
        }});
        if (applyOpenAIState() && canUseOpenAIBridge()) {{
          markReady("openai", "宿主消息桥可用。");
          return;
        }}
        const result = await request("ui/initialize", {{
          appInfo: {{
            name: "scholar-ai-native-handoff-probe",
            version: "0.0.1"
          }},
          appCapabilities: {{}},
          protocolVersion: PROTOCOL_VERSION
        }}, 5000);
        applyHostContext(result.hostContext);
        if (!hostSupportsMessage(result.hostCapabilities)) {{
          throw new Error("Codex host does not advertise ui/message support.");
        }}
        installHostMessageBridge(result);
        notify("ui/notifications/initialized", {{}});
        notify("ui/notifications/size-changed", currentSize());
        markReady("scholarAiMcp.sendMessage", "可发送到 Codex 主栏。");
      }}

      button.addEventListener("click", async () => {{
        if (!state.ready) return;
        button.disabled = true;
        setStatus("发送中...", "sending");
        const text = handoffMessage();
        payloadEl.textContent = text;
        try {{
          applyOpenAIState();
          const result = await sendToHost(text);
          if (result && result.isError) throw new Error("Host returned isError.");
          setStatus(hasRealRequest() ? "已发送到主栏；请看主栏是否开始处理。" : "已发送。请查看 Codex 主栏是否收到测试消息。", "sent");
        }} catch (error) {{
          setStatus(`发送失败：${{error instanceof Error ? error.message : String(error)}}`, "error");
        }} finally {{
          button.disabled = false;
        }}
      }});

      initialize().catch((error) => {{
        setConnection("不可用", "error");
        setStatus(`宿主 widget bridge 不可用：${{error instanceof Error ? error.message : String(error)}}`, "error");
      }});
    }})();
  </script>
</body>
</html>
"""


def _sidebar_app_html() -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scholar AI Sidebar</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f8fafc;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #65728a;
      --line: #d8dfeb;
      --accent: #16745f;
      --warn: #9a5a00;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #11151c;
        --panel: #181f2a;
        --ink: #eef3fb;
        --muted: #aeb8c9;
        --line: #303b4c;
        --accent: #49c7a8;
        --warn: #e6ad58;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 13px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      min-width: 280px;
      max-width: 420px;
      min-height: 100vh;
      padding: 12px;
      display: grid;
      gap: 10px;
      grid-template-rows: auto auto minmax(120px, 1fr) auto auto;
    }}
    .topbar, .answer, .drawers {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .topbar {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      padding: 10px;
    }}
    .brand {{ font-weight: 700; }}
    .status {{
      color: var(--accent);
      white-space: nowrap;
      font-size: 12px;
    }}
    label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin: 0 0 4px;
    }}
    textarea {{
      width: 100%;
      min-height: 78px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px;
      background: var(--panel);
      color: var(--ink);
      font: inherit;
    }}
    .answer {{
      padding: 10px;
      display: grid;
      gap: 8px;
      align-content: start;
    }}
    h1 {{
      font-size: 14px;
      margin: 0;
      letter-spacing: 0;
    }}
    .empty, .evidence-line {{
      color: var(--muted);
      margin: 0;
    }}
    .evidence-line {{
      border-top: 1px solid var(--line);
      padding-top: 8px;
      color: var(--warn);
    }}
    .drawers {{
      padding: 4px 10px;
    }}
    details {{
      border-top: 1px solid var(--line);
      padding: 8px 0;
    }}
    details:first-child {{ border-top: 0; }}
    summary {{
      cursor: default;
      font-weight: 600;
    }}
    ul {{
      margin: 8px 0 0;
      padding-left: 16px;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <main data-schema-version="scholar-ai-sidebar-app/v1" data-status-tool="{SIDEBAR_APP_STATUS_TOOL_NAME}">
    <section class="topbar" aria-label="Project status">
      <div>
        <div class="brand">Scholar AI</div>
        <div class="empty">No project selected</div>
      </div>
      <div class="status">Bridge ready</div>
    </section>
    <section aria-label="Question">
      <label for="scholar-ai-question">Question</label>
      <textarea id="scholar-ai-question" disabled></textarea>
    </section>
    <section class="answer" aria-label="Answer">
      <h1>Answer</h1>
      <p class="empty">No answer loaded.</p>
      <p class="evidence-line">Evidence not checked.</p>
    </section>
    <section class="drawers" aria-label="Details">
      <details>
        <summary>Evidence</summary>
        <ul><li>No evidence bundle loaded.</li></ul>
      </details>
      <details>
        <summary>History</summary>
        <ul><li>No receipt selected.</li></ul>
      </details>
      <details>
        <summary>Actions</summary>
        <ul><li>No queued action.</li></ul>
      </details>
      <details>
        <summary>Handoff</summary>
        <ul><li>No handoff card loaded.</li></ul>
      </details>
    </section>
  </main>
</body>
</html>
"""


def resolve_mcp_tool_profile(value: str | None) -> str:
    """Resolve the MCP tool registration profile.

    Args:
        value: Raw profile name from ``LITASSIST_MCP_TOOL_PROFILE`` or an
            injected test value. Empty input keeps the historical full profile.

    Returns:
        Canonical profile name, either ``full`` or ``minimal``.

    Raises:
        ValueError: If the provided profile is not supported.
    """

    if value is None or not value.strip():
        return MCP_TOOL_PROFILE_FULL
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_MCP_TOOL_PROFILES:
        supported = ", ".join(sorted(SUPPORTED_MCP_TOOL_PROFILES))
        raise ValueError(f"{MCP_TOOL_PROFILE_ENV} must be one of: {supported}")
    return normalized


def experimental_mcp_tools_enabled(value: str | None = None) -> bool:
    """Return whether experimental MCP tools should be exposed.

    Args:
        value: Optional raw flag value. When omitted, the process environment is
            checked.

    Returns:
        ``True`` only for explicit opt-in values.
    """

    raw_value = os.environ.get(EXPERIMENTAL_TOOLS_ENV, "") if value is None else value
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _server_instructions(tool_profile: str, experimental_enabled: bool) -> str:
    """Build profile-aware server instructions without duplicating tool counts."""

    profile_note = (
        "Active tool profile: minimal. Exposes only self-check/navigation, "
        "retrieval/evidence, desktop-visible answer write-back, export, and "
        "safe source-reading tools.\n"
        if tool_profile == MCP_TOOL_PROFILE_MINIMAL
        else "Active tool profile: full.\n"
    )
    experimental_note = (
        "experimental OCR/visual/translate/pack/sandbox exposed because "
        f"{EXPERIMENTAL_TOOLS_ENV}=1 (tools/experimental.py).\n"
        if experimental_enabled
        else "experimental OCR/visual/translate/pack/sandbox hidden until "
        f"{EXPERIMENTAL_TOOLS_ENV}=1.\n"
    )
    typical_chains = (
        "Typical chains: cite-with-evidence = search_refs -> evidence_pack_build "
        "-> evidence_integrity_gate; Claude write-back = agent_request_create "
        "-> agent_resource_read -> agent_result -> answer_receipt_read; "
        "read-code = source.inspect_routes -> source.read_symbols -> source.read_file.\n"
        if tool_profile == MCP_TOOL_PROFILE_MINIMAL
        else "Typical chains: cite-with-evidence = search_refs -> evidence_pack_build "
        "-> evidence_integrity_gate; write = evidence_pack_build -> outline_generate "
        "-> academic_writing_lint -> figures_generate -> export_docx; "
        "read-code = source.inspect_routes -> source.read_symbols -> source.read_file.\n"
    )
    return (
        "Scholar AI (文献助手) local MCP toolbox. "
        "If the user asks to start/open 文献助手 or Scholar AI, call "
        "literature.launch_desktop first; it opens a visible terminal for "
        "the source desktop when no healthy runtime is attached. "
        "On connect: literature.config_status / literature.health_check, "
        "then literature.list_projects to pick a project_id.\n"
        f"{profile_note}"
        "Tool groups: source.* = read-only source inspection (tools/source.py); "
        "literature.* = HTTP to backend literature_assistant/core (tools/runtime.py); "
        "workflow.* / artifact.* = JSON workflow + artifacts (tools/workflow.py); "
        f"{experimental_note}"
        f"{typical_chains}"
        "Full scenario map + tool->code three-hop locator: "
        "source.read_file path=agent_mcp_server/CAPABILITY_MAP.md.\n"
        "Never read/export .env*, credentials, runtime state, logs, browser "
        "profiles, rollback snapshots, .claude/, .codex/."
    )


def _hidden_tool_names_for_profile(
    registered_tool_names: set[str],
    tool_profile: str,
    *,
    experimental_enabled: bool,
) -> set[str]:
    """Return tool names excluded by the resolved MCP exposure profile."""

    hidden_tool_names: set[str] = set()
    if not experimental_enabled:
        hidden_tool_names.update(EXPERIMENTAL_MCP_TOOL_NAMES)
    if tool_profile == MCP_TOOL_PROFILE_MINIMAL:
        hidden_tool_names.update(registered_tool_names.difference(MINIMAL_MCP_TOOL_NAMES))
    return hidden_tool_names


def _filter_workflow_registry(
    tool_registry: dict[str, ToolCallable],
    tool_profile: str,
    *,
    experimental_enabled: bool,
) -> None:
    """Apply the effective MCP profile to one workflow dispatch registry."""

    hidden_tool_names = _hidden_tool_names_for_profile(
        set(tool_registry),
        tool_profile,
        experimental_enabled=experimental_enabled,
    )
    for tool_name in hidden_tool_names:
        tool_registry.pop(tool_name, None)


def _apply_tool_profile(
    mcp: FastMCP,
    tool_profile: str,
    *,
    experimental_enabled: bool,
) -> None:
    """Remove tools that should not be exposed for the active profile."""

    registered_tool_names = {tool.name for tool in mcp._tool_manager.list_tools()}
    if tool_profile == MCP_TOOL_PROFILE_MINIMAL:
        missing = sorted(MINIMAL_MCP_TOOL_NAMES.difference(registered_tool_names))
        if missing:
            raise RuntimeError(f"minimal MCP tool profile is missing registered tools: {missing}")
    hidden_tool_names = _hidden_tool_names_for_profile(
        registered_tool_names,
        tool_profile,
        experimental_enabled=experimental_enabled,
    )

    for tool_name in sorted(hidden_tool_names.intersection(registered_tool_names)):
        mcp._tool_manager.remove_tool(tool_name)

    if tool_profile == MCP_TOOL_PROFILE_MINIMAL:
        resource_manager = getattr(mcp, "_resource_manager", None)
        resources = getattr(resource_manager, "_resources", None)
        if isinstance(resources, dict):
            resources.pop(SIDEBAR_APP_RESOURCE_URI, None)
            resources.pop(NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI, None)


def find_repo_root(start: Path | None = None) -> Path:
    """Find the repository root from private or public source-tree anchors.

    Args:
        start: Optional path to start from. Defaults to this module path.

    Returns:
        Absolute repository root.

    Raises:
        RuntimeError: If the repository root cannot be found.
    """
    env_root = os.environ.get("LITERATURE_ASSISTANT_REPO_ROOT")
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if is_repo_root(candidate):
            return candidate
        raise RuntimeError("LITERATURE_ASSISTANT_REPO_ROOT does not contain Scholar AI repository anchors")

    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if is_repo_root(candidate):
            return candidate
    raise RuntimeError("Could not find repository root from MCP server path")


def create_mcp_server(
    source_tools: SourceTools | None = None,
    runtime_tools: RuntimeTools | None = None,
    workflow_tools: WorkflowTools | None = None,
    experimental_tools: ExperimentalTools | None = None,
    tool_profile: str | None = None,
) -> FastMCP:
    """Create and register the Literature Assistant MCP server.

    Args:
        source_tools: Optional injected source tool implementation for tests.
        runtime_tools: Optional injected runtime tool implementation for tests.
        workflow_tools: Optional injected workflow tool implementation for tests.
        experimental_tools: Optional injected experimental implementation for tests.
        tool_profile: Optional tool exposure profile. When omitted, the value is
            read from ``LITASSIST_MCP_TOOL_PROFILE`` and defaults to ``full``.

    Returns:
        Configured FastMCP server instance.
    """
    resolved_tool_profile = resolve_mcp_tool_profile(
        tool_profile if tool_profile is not None else os.environ.get(MCP_TOOL_PROFILE_ENV)
    )
    experimental_enabled = experimental_mcp_tools_enabled()
    repo_root = find_repo_root()
    audit_root = repo_root / "workspace_artifacts/agent_mcp_workflows/.audit"
    source = source_tools or create_default_source_tools(
        repo_root=repo_root,
        audit=AuditLog(audit_root),
    )
    runtime = runtime_tools or create_default_runtime_tools(
        audit_root=audit_root,
        base_url=os.environ.get("LITERATURE_ASSISTANT_BASE_URL") or None,
        repo_root=repo_root,
    )
    experimental = experimental_tools or create_default_experimental_tools(
        repo_root=repo_root,
        runtime=runtime,
        audit_root=audit_root,
    )
    workflow_registry: dict[str, ToolCallable] = {
        "source.list_tree": source.list_tree,
        "source.search": source.search,
        "source.read_file": source.read_file,
        "source.read_symbols": source.read_symbols,
        "source.inspect_routes": source.inspect_routes,
        "source.find_references": source.find_references,
        "source.explain_entrypoints": source.explain_entrypoints,
        "literature.agent_sidebar_url": runtime.agent_sidebar_url,
        "literature.launch_desktop": runtime.launch_desktop,
        "literature.config_status": runtime.config_status,
        "literature.health_check": runtime.health_check,
        "literature.zotero_attachment_health": runtime.zotero_attachment_health,
        "literature.list_projects": runtime.list_projects,
        "literature.list_materials": runtime.list_materials,
        "literature.read_material": runtime.read_material,
        "literature.get_material_chunks": runtime.get_material_chunks,
        "literature.search_refs": runtime.search_refs,
        "literature.acquisition_status": runtime.acquisition_status,
        "literature.acquisition_search": runtime.acquisition_search,
        "literature.acquisition_search_run": runtime.acquisition_search_run,
        "literature.acquisition_download_queue": runtime.acquisition_download_queue,
        "literature.acquisition_download_run": runtime.acquisition_download_run,
        "literature.acquisition_download_control": runtime.acquisition_download_control,
        "literature.acquisition_gate_resolve": runtime.acquisition_gate_resolve,
        "literature.acquisition_artifact_import": runtime.acquisition_artifact_import,
        "literature.acquisition_import_receipt": runtime.acquisition_import_receipt,
        "literature.knowledge_packages": runtime.knowledge_packages,
        "literature.knowledge_runtime_conformance": runtime.knowledge_runtime_conformance,
        "literature.ocr_status": runtime.ocr_status,
        "literature.ocr_engines": runtime.ocr_engines,
        "literature.ocr_health": runtime.ocr_health,
        "literature.ocr_execution_probe": runtime.ocr_execution_probe,
        "literature.knowledge_context_receipt": runtime.knowledge_context_receipt,
        "literature.wiki_status": runtime.wiki_status,
        "literature.wiki_doctor": runtime.wiki_doctor,
        "literature.wiki_search": runtime.wiki_search,
        "literature.skill_package_status": runtime.skill_package_status,
        "literature.skill_package_search": runtime.skill_package_search,
        "literature.source_vault_status": runtime.source_vault_status,
        "literature.source_vault_search": runtime.source_vault_search,
        "literature.source_vault_read": runtime.source_vault_read,
        "literature.academic_english_status": runtime.academic_english_status,
        "literature.academic_english_search": runtime.academic_english_search,
        "literature.bridge_lexicon_status": runtime.bridge_lexicon_status,
        "literature.bridge_lexicon_read": runtime.bridge_lexicon_read,
        "literature.bridge_lexicon_search": runtime.bridge_lexicon_search,
        "literature.scoring_rules_status": runtime.scoring_rules_status,
        "literature.scoring_rules_read": runtime.scoring_rules_read,
        "literature.scoring_rules_search": runtime.scoring_rules_search,
        "literature.product_docs_status": runtime.product_docs_status,
        "literature.product_docs_read": runtime.product_docs_read,
        "literature.product_docs_search": runtime.product_docs_search,
        "literature.evidence_pack_build": runtime.evidence_pack_build,
        "literature.qrels_review_bundle": runtime.qrels_review_bundle,
        "literature.chat_ask_persisting": runtime.chat_ask_persisting,
        "literature.answer_receipt_list": runtime.answer_receipt_list,
        "literature.answer_receipt_read": runtime.answer_receipt_read,
        "literature.answer_receipt_markdown": runtime.answer_receipt_markdown,
        "literature.answer_receipt_revalidate": runtime.answer_receipt_revalidate,
        "literature.project_scan_folder": runtime.project_scan_folder,
        "literature.figures_candidates": runtime.figures_candidates,
        "literature.figures_generate": runtime.figures_generate,
        "literature.citations_sources": runtime.citations_sources,
        "literature.citations_detect_overlap": runtime.citations_detect_overlap,
        "literature.academic_writing_lint": runtime.academic_writing_lint,
        "literature.outline_generate": runtime.outline_generate,
        "literature.export_annotations_markdown": runtime.export_annotations_markdown,
        "literature.export_docx": runtime.export_docx,
        "literature.agent_bridge_status": runtime.agent_bridge_status,
        "literature.agent_workspace_status": runtime.agent_workspace_status,
        "literature.agent_workspace_requirement": runtime.agent_workspace_requirement,
        "literature.agent_request_create": runtime.agent_request_create,
        "literature.wiki_import": runtime.wiki_import,
        "literature.single_paper_task_create": runtime.single_paper_task_create,
        "literature.single_paper_completion_check": runtime.single_paper_completion_check,
        "literature.agent_request_list": runtime.agent_request_list,
        "literature.agent_request_read": runtime.agent_request_read,
        "literature.agent_handoff_card": runtime.agent_handoff_card,
        "literature.behavior_eval_pack": runtime.behavior_eval_pack,
        "literature.workflow_passport": runtime.workflow_passport,
        "literature.evidence_integrity_gate": runtime.evidence_integrity_gate,
        "literature.research_action_lifecycle": runtime.research_action_lifecycle,
        "literature.workflow_refresh_receipt": runtime.workflow_refresh_receipt,
        "literature.workflow_replay_lineage": runtime.workflow_replay_lineage,
        "literature.workflow_replay_index": runtime.workflow_replay_index,
        "literature.agent_resource_read": runtime.agent_resource_read,
        "literature.agent_progress": runtime.agent_progress,
        "literature.agent_result": runtime.agent_result,
        "literature.agent_fail": runtime.agent_fail,
        "literature.ocr_material": experimental.ocr_material,
        "literature.prepare_visual_review": experimental.prepare_visual_review,
        "literature.translate_pack": experimental.translate_pack,
        "literature.export_project_pack": experimental.export_project_pack,
    }
    _filter_workflow_registry(
        workflow_registry,
        resolved_tool_profile,
        experimental_enabled=experimental_enabled,
    )
    workflow_impl = workflow_tools or create_default_workflow_tools(
        repo_root=repo_root,
        tool_registry=workflow_registry,
        audit_root=audit_root,
    )
    workflow_registry.update(
        {
            "artifact.write_markdown": workflow_impl.write_markdown,
            "artifact.read_artifact": workflow_impl.read_artifact,
            "artifact.list_artifacts": workflow_impl.list_artifacts,
            "workflow.run_python_sandbox": experimental.run_python_sandbox,
        }
    )
    _filter_workflow_registry(
        workflow_registry,
        resolved_tool_profile,
        experimental_enabled=experimental_enabled,
    )
    workflow_impl.tool_registry.clear()
    workflow_impl.tool_registry.update(workflow_registry)
    workflow_impl.interpreter.tool_registry.clear()
    workflow_impl.interpreter.tool_registry.update(workflow_registry)

    mcp = FastMCP(
        name="literature-assistant",
        instructions=_server_instructions(
            tool_profile=resolved_tool_profile,
            experimental_enabled=experimental_enabled,
        ),
    )

    @mcp.resource(
        uri=SIDEBAR_APP_RESOURCE_URI,
        name="scholar-ai-sidebar",
        title="Scholar AI Sidebar",
        description="Narrow host-rendered shell over the existing Scholar AI prompt/tool bridge.",
        mime_type=SIDEBAR_APP_RESOURCE_MIME_TYPE,
        meta={
            "ui": {
                "schemaVersion": "scholar-ai-sidebar-app/v1",
                "statusTool": SIDEBAR_APP_STATUS_TOOL_NAME,
                "prefersBorder": False,
                "csp": {
                    "connectDomains": [],
                    "resourceDomains": [],
                },
            },
        },
    )
    def scholar_ai_sidebar_resource() -> str:
        """Return the static Scholar AI MCP Apps sidebar shell."""
        return _sidebar_app_html()

    @mcp.resource(
        uri=NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
        name="scholar-ai-main-column-handoff",
        title="Scholar AI 主栏交接",
        description=(
            "Host-rendered Scholar AI widget that sends a bounded handoff "
            "message into the Codex main column after the user clicks."
        ),
        mime_type=SIDEBAR_APP_RESOURCE_MIME_TYPE,
        meta={
            "ui": {
                "schemaVersion": NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION,
                "prefersBorder": False,
                "csp": {
                    "connectDomains": [],
                    "resourceDomains": [],
                },
            },
            "openai/widgetDescription": (
                "Scholar AI main-column handoff widget. Sends a bounded sidebar "
                "task handoff to the host conversation only when the user clicks."
            ),
            "openai/widgetPrefersBorder": False,
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            },
        },
    )
    def scholar_ai_native_handoff_probe_resource() -> str:
        """Return a minimal host-rendered handoff probe shell."""
        return _native_handoff_widget_probe_html()

    @mcp.tool(
        name="source.list_tree",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source List Tree",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_list_tree(
        root: str = ".",
        max_depth: int = 3,
        max_entries: int = 500,
    ) -> dict[str, Any]:
        """List allowed source files and directories."""
        return source.list_tree(root=root, max_depth=max_depth, max_entries=max_entries)

    @mcp.tool(
        name="source.search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_search(
        query: str,
        root: str = ".",
        max_results: int = 50,
        case_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Search allowed source files for literal text."""
        return source.search(
            query=query,
            root=root,
            max_results=max_results,
            case_sensitive=case_sensitive,
        )

    @mcp.tool(
        name="source.read_file",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Read File",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_read_file(path: str, max_chars: int = 80000) -> dict[str, Any]:
        """Read an allowed source text file."""
        return source.read_file(path=path, max_chars=max_chars)

    @mcp.tool(
        name="source.read_symbols",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Read Symbols",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_read_symbols(path: str) -> dict[str, Any]:
        """Read top-level Python symbols from an allowed source file."""
        return source.read_symbols(path=path)

    @mcp.tool(
        name="source.inspect_routes",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Inspect Routes",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_inspect_routes(
        root: str = "literature_assistant/core",
        max_routes: int = 200,
    ) -> dict[str, Any]:
        """Inspect FastAPI route decorators without importing modules."""
        return source.inspect_routes(root=root, max_routes=max_routes)

    @mcp.tool(
        name="source.find_references",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Find References",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_find_references(
        symbol: str,
        root: str = ".",
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Find bounded static references to an identifier or literal text."""
        return source.find_references(symbol=symbol, root=root, max_results=max_results)

    @mcp.tool(
        name="source.explain_entrypoints",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Explain Entrypoints",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_explain_entrypoints(
        path: str,
        max_depth: int = 2,
        max_files: int = 30,
    ) -> dict[str, Any]:
        """Sketch imports reachable from a Python entrypoint."""
        return source.explain_entrypoints(path=path, max_depth=max_depth, max_files=max_files)

    @mcp.tool(
        name="literature.agent_sidebar_url",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Sidebar URL",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_sidebar_url(
        project_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the current Codex side-browser URL for `/agent-sidebar`."""
        return runtime.agent_sidebar_url(project_id=project_id, conversation_id=conversation_id)

    @mcp.tool(
        name="literature.launch_desktop",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Launch Scholar AI Desktop",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_launch_desktop(
        initial_path: str | None = None,
        startup_timeout_sec: int = 60,
        force_reopen_after_close: bool = True,
    ) -> dict[str, Any]:
        """Open or attach to the visible Scholar AI / 文献助手 desktop app."""
        return runtime.launch_desktop(
            initial_path=initial_path,
            startup_timeout_sec=startup_timeout_sec,
            force_reopen_after_close=force_reopen_after_close,
        )

    @mcp.tool(
        name="literature.config_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Config Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_config_status() -> dict[str, Any]:
        """Return Literature Assistant backend health."""
        return runtime.config_status()

    @mcp.tool(
        name=SIDEBAR_APP_STATUS_TOOL_NAME,
        structured_output=True,
        annotations=ToolAnnotations(
            title="Sidebar App Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta=SIDEBAR_APP_TOOL_META,
    )
    def literature_sidebar_app_status() -> dict[str, Any]:
        """Return the host-rendered sidebar shell status without generating answers."""
        sidebar_url = runtime.agent_sidebar_url()
        return {
            "is_error": False,
            "schema_version": "scholar-ai-sidebar-status/v1",
            "resource_uri": SIDEBAR_APP_RESOURCE_URI,
            "resource_mime_type": SIDEBAR_APP_RESOURCE_MIME_TYPE,
            "delivery": {
                "default": "codex_side_browser_route",
                "codex_side_browser_route": "active",
                "rendered_sidebar": "host_capability_gated",
                "prompt_tool_bridge": "available",
            },
            "codex_side_browser": {
                "url_tool": "literature.agent_sidebar_url",
                "url": (
                    sidebar_url.get("data", {}).get("url")
                    if isinstance(sidebar_url.get("data"), dict)
                    else None
                ),
                "status": "ready" if sidebar_url.get("is_error") is not True else "unavailable",
                "source": "runtime_descriptor",
                "note": (
                    "Open this URL in the Codex in-app browser. It follows the "
                    "current Scholar AI backend port instead of assuming 8000."
                ),
            },
            "existing_tool_chain": {
                "health": "literature.config_status",
                "projects": "literature.list_projects",
                "answers": [
                    "literature.chat_ask_persisting",
                    "literature.answer_receipt_list",
                    "literature.answer_receipt_read",
                    "literature.answer_receipt_markdown",
                    "literature.answer_receipt_revalidate",
                ],
                "evidence": [
                    "literature.search_refs",
                    "literature.evidence_pack_build",
                    "literature.evidence_integrity_gate",
                    "literature.agent_resource_read",
                    "literature.qrels_review_bundle",
                ],
            },
            "host_gates": {
                "claude_desktop": "pending_resource_render_ui_tool_call_and_main_conversation_read_back",
                "codex_desktop_class": "native_handoff_widget_probe_pending_live_host_test",
            },
            "native_handoff_probe": {
                "tool": NATIVE_HANDOFF_WIDGET_PROBE_TOOL_NAME,
                "resource_uri": NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
                "status": "experimental_probe_only",
                "claim_boundary": "not_a_completed_native_handoff_until_codex_renders_and_main_column_receives_message",
            },
            "backend": runtime.config_status(),
            "sidebar_url": sidebar_url,
        }

    @mcp.tool(
        name=NATIVE_HANDOFF_WIDGET_TOOL_NAME,
        structured_output=False,
        annotations=ToolAnnotations(
            title="Scholar AI 主栏交接",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta=NATIVE_HANDOFF_WIDGET_TOOL_META,
    )
    def literature_codex_handoff_widget(
        request_id: str | None = None,
        project_id: str | None = None,
        receipt_id: str | None = None,
        ref_count: int | None = None,
        note: str | None = None,
    ) -> CallToolResult:
        """Render a Scholar AI handoff widget that can send to the Codex main column."""
        return _build_native_handoff_widget_result(
            request_id=request_id,
            project_id=project_id,
            receipt_id=receipt_id,
            ref_count=ref_count,
            note=note,
        )

    @mcp.tool(
        name=NATIVE_HANDOFF_WIDGET_PROBE_TOOL_NAME,
        structured_output=False,
        annotations=ToolAnnotations(
            title="Scholar AI 主栏交接",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta=NATIVE_HANDOFF_WIDGET_PROBE_TOOL_META,
    )
    def literature_native_handoff_widget_probe(
        request_id: str | None = None,
        project_id: str | None = None,
        receipt_id: str | None = None,
        ref_count: int | None = None,
        note: str | None = None,
    ) -> CallToolResult:
        """Compatibility alias for the Scholar AI Codex handoff widget."""
        return _build_native_handoff_widget_result(
            request_id=request_id,
            project_id=project_id,
            receipt_id=receipt_id,
            ref_count=ref_count,
            note=note,
        )

    def _build_native_handoff_widget_result(
        *,
        request_id: str | None = None,
        project_id: str | None = None,
        receipt_id: str | None = None,
        ref_count: int | None = None,
        note: str | None = None,
    ) -> CallToolResult:
        latest_note: str | None = None
        if request_id is None:
            latest_result = runtime.codex_handoff_latest(project_id=project_id)
            if latest_result.get("is_error") is True:
                latest_note = _bounded_widget_text(str(latest_result.get("message") or "latest handoff unavailable"))
            else:
                latest_data = latest_result.get("data")
                if isinstance(latest_data, dict) and latest_data.get("found") is True:
                    request_id = str(latest_data.get("request_id") or "") or None
                    project_id = project_id or str(latest_data.get("project_id") or "") or None
                    receipt_id = receipt_id or str(latest_data.get("receipt_id") or "") or None
                    latest_ref_count = latest_data.get("ref_count")
                    if ref_count is None and isinstance(latest_ref_count, int):
                        ref_count = latest_ref_count
                    latest_note = "已绑定最新侧栏接手任务。"
                elif isinstance(latest_data, dict):
                    latest_note = _bounded_widget_text(str(latest_data.get("message") or "未找到待接手任务。"))
        bounded_request_id = _bounded_widget_text(request_id, limit=80)
        bounded_project_id = _bounded_widget_text(project_id, limit=80)
        bounded_receipt_id = _bounded_widget_text(receipt_id, limit=120)
        bounded_note = _bounded_widget_text(note, limit=180) or latest_note
        bounded_ref_count = ref_count if isinstance(ref_count, int) and 0 <= ref_count <= 50 else None
        widget_data = {
            "schema_version": NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION,
            "mode": "handoff" if bounded_request_id else "probe",
            "request_id": bounded_request_id or "s74_probe",
            "project_id": bounded_project_id or None,
            "receipt_id": bounded_receipt_id or None,
            "ref_count": bounded_ref_count,
            "note": bounded_note or None,
        }
        structured_content = {
            "is_error": False,
            "schema_version": NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION,
            "resource_uri": NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
            "rendering": "native_mcp_handoff_widget",
            "status": "ready_to_render",
            "claim_boundary": (
                "Native delivery requires the host to render this widget and "
                "the user to click its send button; result write-back still uses "
                "agent_request_read -> agent_result on the same request_id."
            ),
            "widget_data": widget_data,
        }
        mode_text = "交接" if bounded_request_id else "测试"
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=(
                        f"Scholar AI 主栏{mode_text}控件已准备。"
                        "点击控件按钮发送到 Codex 主栏。"
                    ),
                )
            ],
            structuredContent=structured_content,
            _meta={
                "openai/outputTemplate": NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
                "widgetData": widget_data,
            },
        )

    @mcp.tool(
        name="literature.health_check",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Health Check",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_health_check(include_live: bool = False) -> dict[str, Any]:
        """Return passive Scholar AI workflow readiness diagnostics."""
        return runtime.health_check(include_live=include_live)

    @mcp.tool(
        name="literature.zotero_attachment_health",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Zotero Attachment Health",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_zotero_attachment_health(
        zotero_data_dir: str,
        allowed_root: str | None = None,
        min_text_chars: int = 200,
        max_items: int = 500,
        write_reports: bool = True,
    ) -> dict[str, Any]:
        """Return Zotero attachment health diagnostics with optional local reports."""
        return runtime.zotero_attachment_health(
            zotero_data_dir=zotero_data_dir,
            allowed_root=allowed_root,
            min_text_chars=min_text_chars,
            max_items=max_items,
            write_reports=write_reports,
        )

    @mcp.tool(
        name="literature.list_projects",
        structured_output=True,
        annotations=ToolAnnotations(
            title="List Projects",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_list_projects() -> dict[str, Any]:
        """List Literature Assistant projects."""
        return runtime.list_projects()

    @mcp.tool(
        name="literature.list_materials",
        structured_output=True,
        annotations=ToolAnnotations(
            title="List Materials",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_list_materials(project_id: str) -> dict[str, Any]:
        """List materials for a project."""
        return runtime.list_materials(project_id=project_id)

    @mcp.tool(
        name="literature.read_material",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Read Material",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_read_material(material_id: str) -> dict[str, Any]:
        """Read a material record."""
        return runtime.read_material(material_id=material_id)

    @mcp.tool(
        name="literature.get_material_chunks",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Get Material Chunks",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_get_material_chunks(project_id: str, material_id: str) -> dict[str, Any]:
        """Read chunks for a material."""
        return runtime.get_material_chunks(project_id=project_id, material_id=material_id)

    @mcp.tool(
        name="literature.search_refs",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Search Refs",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_search_refs(
        project_id: str,
        query: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search existing project chunks and return refs only."""
        return runtime.search_refs(project_id=project_id, query=query, top_k=top_k)

    @mcp.tool(
        name="literature.acquisition_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Acquisition Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_acquisition_status(
        project_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Read allowlisted sources plus bounded download jobs and access gates."""
        return runtime.acquisition_status(project_id=project_id, limit=limit)

    @mcp.tool(
        name="literature.acquisition_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Acquisition Search",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def literature_acquisition_search(
        project_id: str,
        query: str,
        sources: list[str] | None = None,
        max_results: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> dict[str, Any]:
        """Explicitly search allowlisted metadata sources and persist one bounded run."""
        return runtime.acquisition_search(
            project_id=project_id,
            query=query,
            sources=sources,
            max_results=max_results,
            year_from=year_from,
            year_to=year_to,
        )

    @mcp.tool(
        name="literature.acquisition_search_run",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Acquisition Search Run",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_acquisition_search_run(
        run_id: str,
        candidate_offset: int = 0,
        candidate_limit: int = 10,
    ) -> dict[str, Any]:
        """Read one bounded candidate page from a durable acquisition search run."""
        return runtime.acquisition_search_run(
            run_id=run_id,
            candidate_offset=candidate_offset,
            candidate_limit=candidate_limit,
        )

    @mcp.tool(
        name="literature.acquisition_download_queue",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Acquisition Download Queue",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_acquisition_download_queue(
        project_id: str,
        candidate_id: str,
        access_evidence_id: str,
        max_bytes: int = 100 * 1024 * 1024,
    ) -> dict[str, Any]:
        """Queue one PDF only from exact allowlisted open-access evidence."""
        return runtime.acquisition_download_queue(
            project_id=project_id,
            candidate_id=candidate_id,
            access_evidence_id=access_evidence_id,
            max_bytes=max_bytes,
        )

    @mcp.tool(
        name="literature.acquisition_download_run",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Acquisition Download Run",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def literature_acquisition_download_run(job_id: str) -> dict[str, Any]:
        """Explicitly run or retry one queued allowlisted PDF download."""
        return runtime.acquisition_download_run(job_id=job_id)

    @mcp.tool(
        name="literature.acquisition_download_control",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Acquisition Download Control",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_acquisition_download_control(
        job_id: str,
        action: Literal["pause", "resume", "cancel"],
    ) -> dict[str, Any]:
        """Explicitly pause, resume, or cancel one durable download job."""
        return runtime.acquisition_download_control(job_id=job_id, action=action)

    @mcp.tool(
        name="literature.acquisition_gate_resolve",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Acquisition Gate Resolve",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_acquisition_gate_resolve(
        gate_id: str,
        confirm_user_completed: bool = False,
    ) -> dict[str, Any]:
        """Resolve a visible access gate only after explicit user confirmation."""
        return runtime.acquisition_gate_resolve(
            gate_id=gate_id,
            confirm_user_completed=confirm_user_completed,
        )

    @mcp.tool(
        name="literature.acquisition_artifact_import",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Acquisition Artifact Import",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_acquisition_artifact_import(artifact_id: str) -> dict[str, Any]:
        """Import one validated PDF through the existing material pipeline."""
        return runtime.acquisition_artifact_import(artifact_id=artifact_id)

    @mcp.tool(
        name="literature.acquisition_import_receipt",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Acquisition Import Receipt",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_acquisition_import_receipt(receipt_id: str) -> dict[str, Any]:
        """Read one durable import receipt without repeating ingestion."""
        return runtime.acquisition_import_receipt(receipt_id=receipt_id)

    @mcp.tool(
        name="literature.knowledge_packages",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Knowledge Packages",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_knowledge_packages() -> dict[str, Any]:
        """Return the unified read-only runtime knowledge package registry."""
        return runtime.knowledge_packages()

    @mcp.tool(
        name="literature.knowledge_runtime_conformance",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Knowledge Runtime Conformance",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_knowledge_runtime_conformance() -> dict[str, Any]:
        """Return read-only Knowledge Runtime Pipeline conformance status."""
        return runtime.knowledge_runtime_conformance()

    @mcp.tool(
        name="literature.ocr_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="OCR Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_ocr_status() -> dict[str, Any]:
        """Return the redacted OCR runtime status without running OCR."""
        return runtime.ocr_status()

    @mcp.tool(
        name="literature.ocr_engines",
        structured_output=True,
        annotations=ToolAnnotations(
            title="OCR Engines",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_ocr_engines() -> dict[str, Any]:
        """Return registered OCR engine metadata without running OCR."""
        return runtime.ocr_engines()

    @mcp.tool(
        name="literature.ocr_health",
        structured_output=True,
        annotations=ToolAnnotations(
            title="OCR Health",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_ocr_health(
        engine: str | None = None,
        engine_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a lightweight OCR engine readiness probe without OCR content upload."""
        return runtime.ocr_health(engine=engine, engine_config=engine_config)

    @mcp.tool(
        name="literature.ocr_execution_probe",
        structured_output=True,
        annotations=ToolAnnotations(
            title="OCR Execution Probe",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def literature_ocr_execution_probe(
        confirm_execution: bool = False,
        image_base64: str | None = None,
        image_path: str | None = None,
        engine: str | None = None,
        engine_config: dict[str, Any] | None = None,
        language: str = "en",
        preview_chars: int = 240,
    ) -> dict[str, Any]:
        """Run one explicit OCR execution probe and return bounded proof."""
        return runtime.ocr_execution_probe(
            confirm_execution=confirm_execution,
            image_base64=image_base64,
            image_path=image_path,
            engine=engine,
            engine_config=engine_config,
            language=language,
            preview_chars=preview_chars,
        )

    @mcp.tool(
        name="literature.knowledge_context_receipt",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Knowledge Context Receipt",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_knowledge_context_receipt(
        ref_ids: list[str],
        project_id: str | None = None,
        prompt_name: str = "knowledge_runtime_context",
        max_chars_per_ref: int = 1200,
    ) -> dict[str, Any]:
        """Prove bounded knowledge refs entered model-context input."""
        return runtime.knowledge_context_receipt(
            ref_ids=ref_ids,
            project_id=project_id,
            prompt_name=prompt_name,
            max_chars_per_ref=max_chars_per_ref,
        )

    @mcp.tool(
        name="literature.wiki_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Wiki Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_wiki_status(user_id: str | None = None) -> dict[str, Any]:
        """Return the wiki package runtime status and manifest drilldown."""
        return runtime.wiki_status(user_id=user_id)

    @mcp.tool(
        name="literature.wiki_doctor",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Wiki Doctor",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_wiki_doctor() -> dict[str, Any]:
        """Return read-only wiki integrity diagnostics for recovery agents."""
        return runtime.wiki_doctor()

    @mcp.tool(
        name="literature.wiki_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Wiki Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_wiki_search(
        query: str,
        top_k: int = 8,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Search wiki knowledge and return bounded refs."""
        return runtime.wiki_search(query=query, top_k=top_k, user_id=user_id)

    @mcp.tool(
        name="literature.skill_package_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Skill Package Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_skill_package_status(
        package_id: str = "academic-english-discourse",
    ) -> dict[str, Any]:
        """Return one supported Skill package provenance status."""
        return runtime.skill_package_status(package_id=package_id)

    @mcp.tool(
        name="literature.skill_package_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Skill Package Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_skill_package_search(
        query: str,
        package_id: str = "academic-english-discourse",
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search one supported Skill package and return bounded refs."""
        return runtime.skill_package_search(query=query, package_id=package_id, top_k=top_k)

    @mcp.tool(
        name="literature.source_vault_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Vault Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_source_vault_status(limit: int = 50) -> dict[str, Any]:
        """Return Source Vault package status and recent source records."""
        return runtime.source_vault_status(limit=limit)

    @mcp.tool(
        name="literature.source_vault_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Vault Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_source_vault_search(
        query: str,
        top_k: int = 8,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Search Source Vault chunks and return bounded refs."""
        return runtime.source_vault_search(query=query, top_k=top_k, project_id=project_id)

    @mcp.tool(
        name="literature.source_vault_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Vault Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_source_vault_read(
        ref_id: str,
        project_id: str | None = None,
        max_chars: int = 6000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Read one bounded Source Vault chunk resource."""
        return runtime.source_vault_read(
            ref_id=ref_id,
            project_id=project_id,
            max_chars=max_chars,
            cursor=cursor,
        )

    @mcp.tool(
        name="literature.academic_english_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Academic English Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_academic_english_status() -> dict[str, Any]:
        """Return academic-English knowledge manifest and artifact status."""
        return runtime.academic_english_status()

    @mcp.tool(
        name="literature.academic_english_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Academic English Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_academic_english_search(
        query: str,
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search academic-English knowledge and return bounded refs."""
        return runtime.academic_english_search(query=query, top_k=top_k)

    @mcp.tool(
        name="literature.bridge_lexicon_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Bridge Lexicon Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_bridge_lexicon_status() -> dict[str, Any]:
        """Return CJK bridge lexicon provenance and runtime consumer status."""
        return runtime.bridge_lexicon_status()

    @mcp.tool(
        name="literature.bridge_lexicon_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Bridge Lexicon Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_bridge_lexicon_read() -> dict[str, Any]:
        """Read the bounded CJK bridge lexicon runtime artifact."""
        return runtime.bridge_lexicon_read()

    @mcp.tool(
        name="literature.bridge_lexicon_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Bridge Lexicon Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_bridge_lexicon_search(
        query: str,
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search bridge-lexicon entries and return bounded refs."""
        return runtime.bridge_lexicon_search(query=query, top_k=top_k)

    @mcp.tool(
        name="literature.scoring_rules_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Scoring Rules Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_scoring_rules_status() -> dict[str, Any]:
        """Return scoring-rules JSON config provenance and runtime consumer status."""
        return runtime.scoring_rules_status()

    @mcp.tool(
        name="literature.scoring_rules_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Scoring Rules Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_scoring_rules_read() -> dict[str, Any]:
        """Read the bounded scoring-rules JSON config runtime artifact."""
        return runtime.scoring_rules_read()

    @mcp.tool(
        name="literature.scoring_rules_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Scoring Rules Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_scoring_rules_search(
        query: str,
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search scoring-rules JSON config knowledge and return bounded refs."""
        return runtime.scoring_rules_search(query=query, top_k=top_k)

    @mcp.tool(
        name="literature.product_docs_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Product Docs Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_product_docs_status() -> dict[str, Any]:
        """Return product-docs Markdown provenance and runtime consumer status."""
        return runtime.product_docs_status()

    @mcp.tool(
        name="literature.product_docs_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Product Docs Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_product_docs_read() -> dict[str, Any]:
        """Read the bounded product-docs runtime artifact."""
        return runtime.product_docs_read()

    @mcp.tool(
        name="literature.product_docs_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Product Docs Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_product_docs_search(
        query: str,
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search product-docs Markdown knowledge and return bounded refs."""
        return runtime.product_docs_search(query=query, top_k=top_k)

    @mcp.tool(
        name="literature.evidence_pack_build",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Evidence Pack Build",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_evidence_pack_build(
        project_id: str,
        query: str,
        section_id: str | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Build a query-scoped evidence pack from project refs."""
        return runtime.evidence_pack_build(
            project_id=project_id,
            query=query,
            section_id=section_id,
            top_k=top_k,
        )

    @mcp.tool(
        name="literature.qrels_review_bundle",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Qrels Review Bundle",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_qrels_review_bundle(
        project_id: str,
        evidence_pack_ref: str,
        query: str | None = None,
        max_chunks_per_section: int = 5,
    ) -> dict[str, Any]:
        """Generate candidate-only qrels review artifacts from an evidence pack."""
        return runtime.qrels_review_bundle(
            project_id=project_id,
            evidence_pack_ref=evidence_pack_ref,
            query=query,
            max_chunks_per_section=max_chunks_per_section,
        )

    @mcp.tool(
        name="literature.chat_ask_persisting",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Persisting SmartRead Ask",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def literature_chat_ask_persisting(
        query: str,
        project_id: str,
        session_id: str | None = None,
        tier: str = "balanced",
        answer_origin: str = "internal_smartread",
        generated_in: str = "mcp_sidebar",
        evidence_pack_ref: str | None = None,
    ) -> dict[str, Any]:
        """Ask through SmartRead and save a receipt; tier accepts backend or UX labels."""
        return runtime.chat_ask_persisting(
            query=query,
            project_id=project_id,
            session_id=session_id,
            tier=tier,
            answer_origin=answer_origin,
            generated_in=generated_in,
            evidence_pack_ref=evidence_pack_ref,
        )

    @mcp.tool(
        name="literature.answer_receipt_list",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Answer Receipt List",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_answer_receipt_list(project_id: str, limit: int = 100) -> dict[str, Any]:
        """List project-scoped saved answer receipts."""
        return runtime.answer_receipt_list(project_id=project_id, limit=limit)

    @mcp.tool(
        name="literature.answer_receipt_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Answer Receipt Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_answer_receipt_read(conversation_id: str) -> dict[str, Any]:
        """Read one saved answer receipt and its staleness projection."""
        return runtime.answer_receipt_read(conversation_id=conversation_id)

    @mcp.tool(
        name="literature.answer_receipt_markdown",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Answer Receipt Markdown",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_answer_receipt_markdown(conversation_id: str) -> dict[str, Any]:
        """Render one saved answer receipt as the prompt/tool bridge Markdown projection."""
        return runtime.answer_receipt_markdown(conversation_id=conversation_id)

    @mcp.tool(
        name="literature.answer_receipt_revalidate",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Answer Receipt Revalidate",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_answer_receipt_revalidate(
        conversation_id: str,
        apply: bool = False,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Dry-run or apply revalidation for one saved answer receipt."""
        return runtime.answer_receipt_revalidate(
            conversation_id=conversation_id,
            apply=apply,
            top_k=top_k,
        )

    @mcp.tool(
        name="literature.project_scan_folder",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Project Scan Folder",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_project_scan_folder(
        project_id: str,
        scan_mode: str = "fast",
        batch_size: int = 24,
        max_workers: int = 8,
    ) -> dict[str, Any]:
        """Submit project source-folder ingestion as a runtime job."""
        return runtime.project_scan_folder(
            project_id=project_id,
            scan_mode=scan_mode,
            batch_size=batch_size,
            max_workers=max_workers,
        )

    @mcp.tool(
        name="literature.figures_candidates",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Figure Candidates",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_figures_candidates(
        project_id: str,
        limit: int = 20,
        pixel_only: bool = False,
        render_pdf_fallback: bool = True,
        query: str | None = None,
    ) -> dict[str, Any]:
        """List backend-derived figure/table candidates."""
        return runtime.figures_candidates(
            project_id=project_id,
            limit=limit,
            pixel_only=pixel_only,
            render_pdf_fallback=render_pdf_fallback,
            query=query,
        )

    @mcp.tool(
        name="literature.figures_generate",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Generate Figures",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_figures_generate(
        project_id: str,
        candidate_ids: list[str] | None = None,
        max_items: int = 1,
        kind: str | None = None,
        overwrite_existing: bool = False,
    ) -> dict[str, Any]:
        """Materialize existing pixel-backed figure/table candidates."""
        return runtime.figures_generate(
            project_id=project_id,
            candidate_ids=candidate_ids,
            max_items=max_items,
            kind=kind,
            overwrite_existing=overwrite_existing,
        )

    @mcp.tool(
        name="literature.citations_sources",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Citation Sources",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_citations_sources(project_id: str) -> dict[str, Any]:
        """List backend-managed citation source metadata."""
        return runtime.citations_sources(project_id=project_id)

    @mcp.tool(
        name="literature.citations_detect_overlap",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Citation Overlap Diagnostic",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_citations_detect_overlap(
        project_id: str,
        anchors: list[dict[str, Any]],
        threshold: float = 0.7,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        """Detect citation anchors that reuse the same or similar evidence."""
        return runtime.citations_detect_overlap(
            project_id=project_id,
            anchors=anchors,
            threshold=threshold,
            draft_id=draft_id,
        )

    @mcp.tool(
        name="literature.academic_writing_lint",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Academic Writing Lint",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_academic_writing_lint(
        text: str | None = None,
        html: str | None = None,
        content_type: str = "manuscript",
        language: str = "auto",
        required_sections: list[str] | None = None,
        require_evidence_refs: bool = True,
        require_figure_table_formula_refs: bool = False,
        style_profile: str | None = None,
        audit_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check scholarly writing quality before export or submission."""
        return runtime.academic_writing_lint(
            text=text,
            html=html,
            content_type=content_type,
            language=language,
            required_sections=required_sections,
            require_evidence_refs=require_evidence_refs,
            require_figure_table_formula_refs=require_figure_table_formula_refs,
            style_profile=style_profile,
            audit_context=audit_context,
        )

    @mcp.tool(
        name="literature.outline_generate",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Outline Generate",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def literature_outline_generate(
        project_id: str,
        topic: str,
        content_type: str = "academic",
        target_length: int | None = None,
        focus_areas: list[str] | None = None,
        existing_materials: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate an evidence-grounded writing outline."""
        return runtime.outline_generate(
            project_id=project_id,
            topic=topic,
            content_type=content_type,
            target_length=target_length,
            focus_areas=focus_areas,
            existing_materials=existing_materials,
        )

    @mcp.tool(
        name="literature.export_annotations_markdown",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Export Annotations Markdown",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_export_annotations_markdown(material_id: str) -> dict[str, Any]:
        """Export material annotations as Markdown."""
        return runtime.export_annotations_markdown(material_id=material_id)

    @mcp.tool(
        name="literature.export_docx",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Export DOCX",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_export_docx(
        html: str,
        title: str,
        style_profile: str = "gb_t_7714_review",
        verify_with_word: bool = False,
        project_id: str | None = None,
        require_action_preflight: bool = False,
    ) -> dict[str, Any]:
        """Export scholarly HTML as a DOCX workflow artifact."""
        return runtime.export_docx(
            html=html,
            title=title,
            style_profile=style_profile,
            verify_with_word=verify_with_word,
            project_id=project_id,
            require_action_preflight=require_action_preflight,
        )

    @mcp.tool(
        name="literature.journal_style_spec_draft",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Journal Style Draft",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_journal_style_spec_draft(
        project_id: str,
        journal_name: str,
        spec_text: str,
    ) -> dict[str, Any]:
        """Create a reviewable project-scoped journal style profile draft."""
        return runtime.journal_style_spec_draft(
            project_id=project_id,
            journal_name=journal_name,
            spec_text=spec_text,
        )

    @mcp.tool(
        name="literature.journal_style_spec_confirm",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Journal Style Confirm",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_journal_style_spec_confirm(
        project_id: str,
        draft_id: str,
        confirmed_by: str = "mcp",
    ) -> dict[str, Any]:
        """Confirm a project-scoped journal style profile draft."""
        return runtime.journal_style_spec_confirm(
            project_id=project_id,
            draft_id=draft_id,
            confirmed_by=confirmed_by,
        )

    @mcp.tool(
        name="literature.agent_bridge_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Bridge Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_bridge_status(limit: int = 20) -> dict[str, Any]:
        """Read the runtime-backed agent bridge status."""
        return runtime.agent_bridge_status(limit=limit)

    @mcp.tool(
        name="literature.agent_workspace_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Workspace Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_workspace_status(
        artifact_limit: int = 200,
        audit_limit: int = 200,
    ) -> dict[str, Any]:
        """Read the Agent Workspace status and workspace recovery state."""
        return runtime.agent_workspace_status(artifact_limit=artifact_limit, audit_limit=audit_limit)

    @mcp.tool(
        name="literature.agent_workspace_requirement",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Workspace Requirement",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_workspace_requirement(
        requirement_id: str,
    ) -> dict[str, Any]:
        """Read one Agent Workspace requirement-to-evidence drilldown."""
        return runtime.agent_workspace_requirement(requirement_id=requirement_id)

    @mcp.tool(
        name="literature.agent_request_create",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Request Create",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_agent_request_create(
        intent: str,
        user_text: str = "",
        project_id: str | None = None,
        runtime_session_id: str | None = None,
        chat_session_id: str | None = None,
        route: str | None = None,
        resource_refs: list[dict[str, Any]] | None = None,
        agent_host: str = "mcp",
        source: str = "mcp",
        max_chars: int = 12000,
        max_chunks: int = 12,
        smart_read_conversation: bool = False,
        wiki_candidate: bool = False,
        graph_candidate: bool = False,
        evolution_capture: bool = True,
    ) -> dict[str, Any]:
        """Create a frontend-visible runtime job for external agent work."""
        return runtime.agent_request_create(
            intent=intent,
            user_text=user_text,
            project_id=project_id,
            runtime_session_id=runtime_session_id,
            chat_session_id=chat_session_id,
            route=route,
            resource_refs=resource_refs,
            agent_host=agent_host,
            source=source,
            max_chars=max_chars,
            max_chunks=max_chunks,
            smart_read_conversation=smart_read_conversation,
            wiki_candidate=wiki_candidate,
            graph_candidate=graph_candidate,
            evolution_capture=evolution_capture,
        )

    @mcp.tool(
        name="literature.wiki_import",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Import Markdown to Wiki",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_wiki_import(
        source_paths: list[str],
        dry_run: bool = True,
        confirm_write: bool = False,
        overwrite: bool = False,
        kind: str = "synthesis",
        status: str = "draft",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Import local Markdown files into private wiki pages."""
        return runtime.wiki_import(
            source_paths=source_paths,
            dry_run=dry_run,
            confirm_write=confirm_write,
            overwrite=overwrite,
            kind=kind,
            status=status,
            user_id=user_id,
        )

    @mcp.tool(
        name="literature.single_paper_task_create",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Single Paper Task Create",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_single_paper_task_create(
        project_id: str,
        material_id: str,
        task_goal: str = "生成单篇论文深度精读、写作借鉴要点、可导出 Word 的结构化草稿",
        output_language: str = "zh",
        target_document: str = "word_draft",
        create_agent_request: bool = True,
        agent_host: str = "mcp",
        source: str = "mcp",
        max_chars: int = 12000,
        max_chunks: int = 12,
    ) -> dict[str, Any]:
        """Create a dynamic single-paper deep-reading task instance."""
        return runtime.single_paper_task_create(
            project_id=project_id,
            material_id=material_id,
            task_goal=task_goal,
            output_language=output_language,
            target_document=target_document,
            create_agent_request=create_agent_request,
            agent_host=agent_host,
            source=source,
            max_chars=max_chars,
            max_chunks=max_chunks,
        )

    @mcp.tool(
        name="literature.single_paper_completion_check",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Single Paper Completion Check",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_single_paper_completion_check(
        output_text: str,
        task_manifest: dict[str, Any],
        required_output_sections: list[str] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        figure_table_refs: list[dict[str, Any]] | None = None,
        lint_passed: bool = False,
        docx_artifact_path: str | None = None,
        sentinel: str = "待补充",
    ) -> dict[str, Any]:
        """Validate a completed single-paper deep-reading draft."""
        return runtime.single_paper_completion_check(
            output_text=output_text,
            task_manifest=task_manifest,
            required_output_sections=required_output_sections,
            evidence_refs=evidence_refs,
            figure_table_refs=figure_table_refs,
            lint_passed=lint_passed,
            docx_artifact_path=docx_artifact_path,
            sentinel=sentinel,
        )

    @mcp.tool(
        name="literature.agent_request_list",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Request List",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_request_list(
        status: str | None = None,
        project_id: str | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List runtime-visible agent requests."""
        return runtime.agent_request_list(status=status, project_id=project_id, source=source, limit=limit)

    @mcp.tool(
        name="literature.agent_request_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Request Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_request_read(request_id: str) -> dict[str, Any]:
        """Read one runtime-visible agent request."""
        return runtime.agent_request_read(request_id=request_id)

    @mcp.tool(
        name="literature.agent_handoff_card",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Handoff Card",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_handoff_card(request_id: str) -> dict[str, Any]:
        """Read a resumable handoff card for one runtime-visible agent request."""
        return runtime.agent_handoff_card(request_id=request_id)

    @mcp.tool(
        name="literature.behavior_eval_pack",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Behavior Eval Pack",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_behavior_eval_pack(
        observations: list[dict[str, Any]] | None = None,
        include_cases: bool = True,
        write_record: bool = True,
    ) -> dict[str, Any]:
        """Run deterministic local red-flag evals for MCP and agent outputs."""
        return runtime.behavior_eval_pack(
            observations=observations,
            include_cases=include_cases,
            write_record=write_record,
        )

    @mcp.tool(
        name="literature.workflow_passport",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Passport",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_workflow_passport(
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Read the runtime workflow passport projection."""
        return runtime.workflow_passport(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )

    @mcp.tool(
        name="literature.evidence_integrity_gate",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Evidence Integrity Gate",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_evidence_integrity_gate(
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        query: str | None = None,
        evidence_pack_ref: str | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        retrieval_diagnostics: dict[str, Any] | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Read runtime or query-scoped evidence integrity diagnostics."""
        return runtime.evidence_integrity_gate(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            query=query,
            evidence_pack_ref=evidence_pack_ref,
            evidence_refs=evidence_refs,
            retrieval_diagnostics=retrieval_diagnostics,
            limit=limit,
        )

    @mcp.tool(
        name="literature.research_action_lifecycle",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Research Action Lifecycle",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_research_action_lifecycle(
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Read the runtime research action lifecycle projection."""
        return runtime.research_action_lifecycle(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )

    @mcp.tool(
        name="literature.workflow_refresh_receipt",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Refresh Receipt",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_workflow_refresh_receipt(
        job_id: str,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        """Read a persisted workflow refresh/replay receipt for one runtime job."""
        return runtime.workflow_refresh_receipt(job_id=job_id, receipt_id=receipt_id)

    @mcp.tool(
        name="literature.workflow_replay_lineage",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Replay Lineage",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_workflow_replay_lineage(
        job_id: str,
        limit: int = 12,
    ) -> dict[str, Any]:
        """Read compact workflow replay lineage for one runtime job."""
        return runtime.workflow_replay_lineage(job_id=job_id, limit=limit)

    @mcp.tool(
        name="literature.workflow_replay_index",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Replay Index",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_workflow_replay_index(
        project_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        action_id: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Read a bounded cross-job workflow replay index for recovery."""
        return runtime.workflow_replay_index(
            project_id=project_id,
            session_id=session_id,
            status=status,
            action_id=action_id,
            limit=limit,
        )

    @mcp.tool(
        name="literature.agent_resource_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Resource Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_resource_read(
        ref_id: str,
        project_id: str | None = None,
        max_chars: int = 6000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Read a bounded resource ref for an agent request."""
        return runtime.agent_resource_read(
            ref_id=ref_id,
            project_id=project_id,
            max_chars=max_chars,
            cursor=cursor,
        )

    @mcp.tool(
        name="literature.agent_progress",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Progress",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_agent_progress(
        request_id: str,
        stage: str,
        message: str,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write a short progress delta to an agent request job."""
        return runtime.agent_progress(
            request_id=request_id,
            stage=stage,
            message=message,
            progress=progress,
            data=data,
        )

    @mcp.tool(
        name="literature.agent_result",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Result",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_agent_result(
        request_id: str,
        text: str = "",
        content: dict[str, Any] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        wiki_refs: list[dict[str, Any]] | None = None,
        graph_patch_refs: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write final agent output to runtime artifacts."""
        return runtime.agent_result(
            request_id=request_id,
            text=text,
            content=content,
            evidence_refs=evidence_refs,
            wiki_refs=wiki_refs,
            graph_patch_refs=graph_patch_refs,
            metadata=metadata,
        )

    @mcp.tool(
        name="literature.agent_fail",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Fail",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_agent_fail(request_id: str, error: str) -> dict[str, Any]:
        """Fail a runtime-visible agent request job."""
        return runtime.agent_fail(request_id=request_id, error=error)

    @mcp.tool(
        name="literature.ocr_material",
        structured_output=True,
        annotations=ToolAnnotations(
            title="OCR Material",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_ocr_material(
        material_id: str,
        pages: list[int] | None = None,
        ocr_language: str = "eng",
    ) -> dict[str, Any]:
        """Experimental OCR entrypoint; disabled by default."""
        return experimental.ocr_material(
            material_id=material_id,
            pages=pages,
            ocr_language=ocr_language,
        )

    @mcp.tool(
        name="literature.prepare_visual_review",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Prepare Visual Review",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_prepare_visual_review(
        project_id: str,
        query: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Experimental visual review pack preparation; disabled by default."""
        return experimental.prepare_visual_review(project_id=project_id, query=query, top_k=top_k)

    @mcp.tool(
        name="literature.translate_pack",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Translate Pack",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def literature_translate_pack(
        project_id: str,
        target_language: str,
        query: str | None = None,
        top_k: int = 8,
        use_model: bool = True,
    ) -> dict[str, Any]:
        """Experimental translation pack entrypoint; disabled by default."""
        return experimental.translate_pack(
            project_id=project_id,
            target_language=target_language,
            query=query,
            top_k=top_k,
            use_model=use_model,
        )

    @mcp.tool(
        name="literature.export_project_pack",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Export Project Pack",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_export_project_pack(
        project_id: str,
        include_search_preview: bool = False,
        query: str = "",
    ) -> dict[str, Any]:
        """Experimental project pack export; disabled by default."""
        return experimental.export_project_pack(
            project_id=project_id,
            include_search_preview=include_search_preview,
            query=query,
        )

    @mcp.tool(
        name="workflow.create_plan",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Create Plan",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def workflow_create_plan(
        goal: str,
        suggested_steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a JSON workflow plan skeleton."""
        return workflow_impl.create_plan(goal=goal, suggested_steps=suggested_steps)

    @mcp.tool(
        name="workflow.write_json_workflow",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Write JSON",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def workflow_write_json_workflow(
        path: str,
        workflow: dict[str, Any],
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Write a JSON workflow artifact."""
        return workflow_impl.write_json_workflow(path=path, workflow=workflow, overwrite=overwrite)

    @mcp.tool(
        name="workflow.run_json_workflow",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Run JSON",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def workflow_run_json_workflow(
        workflow: dict[str, Any] | None = None,
        path: str | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run an inline or artifact-backed JSON workflow."""
        return workflow_impl.run_json_workflow(workflow=workflow, path=path, input_data=input_data)

    @mcp.tool(
        name="workflow.run_python_sandbox",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Run Python Sandbox",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def workflow_run_python_sandbox(script: dict[str, Any]) -> dict[str, Any]:
        """Experimental Python sandbox entrypoint; disabled by default."""
        return experimental.run_python_sandbox(script=script)

    @mcp.tool(
        name="artifact.write_markdown",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Artifact Write Markdown",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def artifact_write_markdown(
        path: str,
        content: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Write a Markdown artifact under the workflow workspace."""
        return workflow_impl.write_markdown(path=path, content=content, overwrite=overwrite)

    @mcp.tool(
        name="artifact.read_artifact",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Artifact Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def artifact_read_artifact(path: str, max_chars: int = 120000) -> dict[str, Any]:
        """Read a text artifact from the workflow workspace."""
        return workflow_impl.read_artifact(path=path, max_chars=max_chars)

    @mcp.tool(
        name="artifact.list_artifacts",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Artifact List",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def artifact_list_artifacts(max_entries: int = 200) -> dict[str, Any]:
        """List workflow artifacts."""
        return workflow_impl.list_artifacts(max_entries=max_entries)

    _apply_tool_profile(
        mcp,
        resolved_tool_profile,
        experimental_enabled=experimental_enabled,
    )
    return mcp


def main() -> None:
    """Run the MCP server over stdio."""
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
