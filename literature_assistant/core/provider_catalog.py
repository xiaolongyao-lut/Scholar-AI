"""Provider + model catalog (extracted from chat_router.py per S6).

S6 (`docs/plans/active/2026-05-13-settings-unified-api-config-plan.md`)
moves the static MODEL_CATALOG out of the chat router so the router
itself stays focused on request handling. The catalog still ships the
same data and the same `/chat/providers` + `/chat/models` endpoints in
chat_router.py keep returning it (with an RFC 9745 `Deprecation` HTTP
header to signal that those endpoints are compatibility-only and the
canonical config flow is now `/api/chat/config` + Settings-driven
backend resolution).

Per `2026-05-15-post-discussion-carryover-plan.md` D-CO-9:
- `MODEL_CATALOG` lives here (active backend module, importable from
  the runtime path) so the runtime never depends on
  `workspace_references/`.
- `workspace_references/provider_catalog_archive.py` carries the same
  data as a non-runtime archive for documentation / future "quick
  fill" UX, but is **not** imported by any runtime code.
- No `Sunset` HTTP header is added because no removal date is set
  yet (RFC 8594).

Public surface (kept stable for chat_router import):
- `ModelInfo` Pydantic model
- `ProviderInfo` Pydantic model
- `MODEL_CATALOG: list[ProviderInfo]`
- `SUPPORTED_PROVIDERS: list[ModelInfo]` (flat fallback list)
"""

from __future__ import annotations

from pydantic import BaseModel


class ModelInfo(BaseModel):
    """LLM model information."""

    id: str
    name: str
    provider: str
    default_base_url: str = ""
    context_window: int = 0
    description: str = ""


class ProviderInfo(BaseModel):
    """Provider with grouped models."""

    provider: str
    display_name: str
    default_base_url: str
    api_type: str = "openai-compatible"
    auth_tip: str = ""
    models: list[ModelInfo]


# Comprehensive model catalog — learned from openhanako known-models + quivr LLMModelConfig
MODEL_CATALOG: list[ProviderInfo] = [
    ProviderInfo(
        provider="DeepSeek",
        display_name="DeepSeek",
        default_base_url="https://api.deepseek.com",
        auth_tip="使用 DeepSeek 开放平台的 API Key (sk-...)",
        models=[
            ModelInfo(id="deepseek-chat", name="DeepSeek-V3", provider="DeepSeek", default_base_url="https://api.deepseek.com", context_window=64000, description="通用对话模型，性价比高"),
            ModelInfo(id="deepseek-reasoner", name="DeepSeek-R1", provider="DeepSeek", default_base_url="https://api.deepseek.com", context_window=64000, description="推理增强模型，适合复杂分析"),
        ],
    ),
    ProviderInfo(
        provider="OpenAI",
        display_name="OpenAI",
        default_base_url="https://api.openai.com",
        auth_tip="使用 OpenAI 平台的 API Key (sk-...)",
        models=[
            ModelInfo(id="gpt-4o", name="GPT-4o", provider="OpenAI", default_base_url="https://api.openai.com", context_window=128000, description="旗舰多模态模型"),
            ModelInfo(id="gpt-4o-mini", name="GPT-4o Mini", provider="OpenAI", default_base_url="https://api.openai.com", context_window=128000, description="轻量快速，适合日常任务"),
            ModelInfo(id="gpt-4.1", name="GPT-4.1", provider="OpenAI", default_base_url="https://api.openai.com", context_window=1047576, description="最新旗舰模型，超长上下文"),
            ModelInfo(id="gpt-4.1-mini", name="GPT-4.1 Mini", provider="OpenAI", default_base_url="https://api.openai.com", context_window=1047576, description="轻量版旗舰，兼顾速度与能力"),
            ModelInfo(id="gpt-4.1-nano", name="GPT-4.1 Nano", provider="OpenAI", default_base_url="https://api.openai.com", context_window=1047576, description="极速低成本选项"),
            ModelInfo(id="o3-mini", name="o3-mini", provider="OpenAI", default_base_url="https://api.openai.com", context_window=200000, description="推理模型，适合数学/代码分析"),
        ],
    ),
    ProviderInfo(
        provider="Claude",
        display_name="Anthropic Claude",
        default_base_url="https://api.anthropic.com",
        api_type="anthropic",
        auth_tip="使用 Anthropic 的 API Key。注意：如使用 OpenAI 兼容代理（如 OpenRouter），请选择'OpenAI 兼容'",
        models=[
            ModelInfo(id="claude-sonnet-4-20250514", name="Claude Sonnet 4", provider="Claude", default_base_url="https://api.anthropic.com", context_window=200000, description="编程与分析能力极强"),
            ModelInfo(id="claude-opus-4-20250514", name="Claude Opus 4", provider="Claude", default_base_url="https://api.anthropic.com", context_window=200000, description="最强模型，适合深度学术研究"),
            ModelInfo(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", provider="Claude", default_base_url="https://api.anthropic.com", context_window=200000, description="快速轻量，成本最低"),
        ],
    ),
    ProviderInfo(
        provider="Gemini",
        display_name="Google Gemini",
        default_base_url="https://generativelanguage.googleapis.com",
        auth_tip="使用 Google AI Studio 的 API Key",
        models=[
            ModelInfo(id="gemini-2.5-flash", name="Gemini 2.5 Flash", provider="Gemini", default_base_url="https://generativelanguage.googleapis.com", context_window=1048576, description="超长上下文，性价比极高"),
            ModelInfo(id="gemini-2.5-pro", name="Gemini 2.5 Pro", provider="Gemini", default_base_url="https://generativelanguage.googleapis.com", context_window=1048576, description="最强推理能力"),
            ModelInfo(id="gemini-2.0-flash", name="Gemini 2.0 Flash", provider="Gemini", default_base_url="https://generativelanguage.googleapis.com", context_window=1048576, description="上一代快速模型"),
        ],
    ),
    ProviderInfo(
        provider="Qwen",
        display_name="通义千问（阿里云）",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode",
        auth_tip="使用阿里云 DashScope 的 API Key (sk-...)",
        models=[
            ModelInfo(id="qwen-plus", name="Qwen Plus", provider="Qwen", default_base_url="https://dashscope.aliyuncs.com/compatible-mode", context_window=131072, description="通用高性能模型"),
            ModelInfo(id="qwen-turbo", name="Qwen Turbo", provider="Qwen", default_base_url="https://dashscope.aliyuncs.com/compatible-mode", context_window=131072, description="快速低成本"),
            ModelInfo(id="qwen-max", name="Qwen Max", provider="Qwen", default_base_url="https://dashscope.aliyuncs.com/compatible-mode", context_window=32768, description="最强旗舰模型"),
            ModelInfo(id="qwen-long", name="Qwen Long", provider="Qwen", default_base_url="https://dashscope.aliyuncs.com/compatible-mode", context_window=10000000, description="千万字超长文档处理"),
        ],
    ),
    ProviderInfo(
        provider="Zhipu",
        display_name="智谱 GLM",
        default_base_url="https://open.bigmodel.cn/api/paas",
        auth_tip="使用智谱 AI 开放平台的 API Key",
        models=[
            ModelInfo(id="glm-4-plus", name="GLM-4 Plus", provider="Zhipu", default_base_url="https://open.bigmodel.cn/api/paas", context_window=128000, description="旗舰对话模型"),
            ModelInfo(id="glm-4-flash", name="GLM-4 Flash", provider="Zhipu", default_base_url="https://open.bigmodel.cn/api/paas", context_window=128000, description="免费快速模型"),
        ],
    ),
    ProviderInfo(
        provider="Doubao",
        display_name="豆包（字节跳动）",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        auth_tip="使用火山引擎 ARK 平台的 API Key。模型 ID 可填接入点 ID (ep-xxx) 或官方模型名称（如 doubao-pro-32k）。Base URL 填写 https://ark.cn-beijing.volces.com/api/v3 即可，无需加 /responses 后缀。",
        models=[
            ModelInfo(id="ep-xxx", name="豆包接入点", provider="Doubao", default_base_url="https://ark.cn-beijing.volces.com/api/v3", context_window=128000, description="填入火山引擎控制台的接入点 ID (ep-xxxxxxxx)"),
            ModelInfo(id="doubao-pro-32k", name="豆包 Pro 32K", provider="Doubao", default_base_url="https://ark.cn-beijing.volces.com/api/v3", context_window=32000, description="豆包 Pro 旗舰对话模型"),
            ModelInfo(id="doubao-lite-32k", name="豆包 Lite 32K", provider="Doubao", default_base_url="https://ark.cn-beijing.volces.com/api/v3", context_window=32000, description="豆包 Lite 轻量对话模型"),
        ],
    ),
    ProviderInfo(
        provider="Moonshot",
        display_name="Kimi（月之暗面）",
        default_base_url="https://api.moonshot.cn",
        auth_tip="使用 Moonshot 平台的 API Key (sk-...)",
        models=[
            ModelInfo(id="moonshot-v1-auto", name="Kimi Auto", provider="Moonshot", default_base_url="https://api.moonshot.cn", context_window=128000, description="自动选择上下文长度"),
            ModelInfo(id="moonshot-v1-128k", name="Kimi 128K", provider="Moonshot", default_base_url="https://api.moonshot.cn", context_window=128000, description="超长上下文"),
        ],
    ),
    ProviderInfo(
        provider="SiliconFlow",
        display_name="SiliconFlow（硅基流动）",
        default_base_url="https://api.siliconflow.cn",
        auth_tip="聚合平台，支持多种开源模型，API Key 来自 SiliconFlow 控制台",
        models=[
            ModelInfo(id="deepseek-ai/DeepSeek-V3", name="DeepSeek-V3 (SiliconFlow)", provider="SiliconFlow", default_base_url="https://api.siliconflow.cn", context_window=64000, description="通过 SiliconFlow 调用 DeepSeek"),
            ModelInfo(id="deepseek-ai/DeepSeek-R1", name="DeepSeek-R1 (SiliconFlow)", provider="SiliconFlow", default_base_url="https://api.siliconflow.cn", context_window=64000, description="通过 SiliconFlow 调用 R1"),
            ModelInfo(id="Qwen/Qwen2.5-72B-Instruct", name="Qwen 2.5 72B (SiliconFlow)", provider="SiliconFlow", default_base_url="https://api.siliconflow.cn", context_window=32768, description="通过 SiliconFlow 调用千问"),
        ],
    ),
    ProviderInfo(
        provider="OpenRouter",
        display_name="OpenRouter（聚合代理）",
        default_base_url="https://openrouter.ai/api",
        auth_tip="一个 Key 访问所有主流模型，从 openrouter.ai 获取 API Key",
        models=[
            ModelInfo(id="deepseek/deepseek-chat-v3-0324", name="DeepSeek V3 (OpenRouter)", provider="OpenRouter", default_base_url="https://openrouter.ai/api", context_window=64000, description="通过 OpenRouter 代理"),
            ModelInfo(id="google/gemini-2.5-flash-preview", name="Gemini 2.5 Flash (OpenRouter)", provider="OpenRouter", default_base_url="https://openrouter.ai/api", context_window=1048576, description="通过 OpenRouter 代理"),
            ModelInfo(id="anthropic/claude-sonnet-4", name="Claude Sonnet 4 (OpenRouter)", provider="OpenRouter", default_base_url="https://openrouter.ai/api", context_window=200000, description="通过 OpenRouter 代理"),
        ],
    ),
    ProviderInfo(
        provider="Groq",
        display_name="Groq（超快推理）",
        default_base_url="https://api.groq.com/openai/v1",
        auth_tip="从 console.groq.com 获取免费 API Key，推理速度比一般云服务快 10-20x",
        models=[
            ModelInfo(id="llama-3.3-70b-versatile", name="Llama 3.3 70B", provider="Groq", default_base_url="https://api.groq.com/openai/v1", context_window=128000, description="Meta 最新旗舰开源模型，速度极快"),
            ModelInfo(id="llama-3.1-8b-instant", name="Llama 3.1 8B Instant", provider="Groq", default_base_url="https://api.groq.com/openai/v1", context_window=128000, description="极速轻量，适合高频对话"),
            ModelInfo(id="mixtral-8x7b-32768", name="Mixtral 8x7B", provider="Groq", default_base_url="https://api.groq.com/openai/v1", context_window=32768, description="Mistral 混合专家架构"),
            ModelInfo(id="gemma2-9b-it", name="Gemma 2 9B", provider="Groq", default_base_url="https://api.groq.com/openai/v1", context_window=8192, description="Google Gemma 2 开源模型"),
        ],
    ),
    ProviderInfo(
        provider="Mistral",
        display_name="Mistral AI（欧洲）",
        default_base_url="https://api.mistral.ai/v1",
        auth_tip="从 console.mistral.ai 获取 API Key，数据存储在欧洲，符合 GDPR",
        models=[
            ModelInfo(id="mistral-small-latest", name="Mistral Small", provider="Mistral", default_base_url="https://api.mistral.ai/v1", context_window=32768, description="轻量高效，性价比高"),
            ModelInfo(id="mistral-medium-latest", name="Mistral Medium", provider="Mistral", default_base_url="https://api.mistral.ai/v1", context_window=131072, description="均衡性能，超长上下文"),
            ModelInfo(id="mistral-large-latest", name="Mistral Large", provider="Mistral", default_base_url="https://api.mistral.ai/v1", context_window=131072, description="旗舰模型，适合复杂推理"),
            ModelInfo(id="codestral-latest", name="Codestral", provider="Mistral", default_base_url="https://api.mistral.ai/v1", context_window=32768, description="专为代码生成优化"),
        ],
    ),
    ProviderInfo(
        provider="Perplexity",
        display_name="Perplexity（联网搜索）",
        default_base_url="https://api.perplexity.ai",
        auth_tip="从 perplexity.ai/settings/api 获取 API Key，sonar 系列模型自带实时联网搜索",
        models=[
            ModelInfo(id="sonar", name="Sonar", provider="Perplexity", default_base_url="https://api.perplexity.ai", context_window=127072, description="联网搜索，回答实时信息"),
            ModelInfo(id="sonar-pro", name="Sonar Pro", provider="Perplexity", default_base_url="https://api.perplexity.ai", context_window=127072, description="高级联网搜索，更深入分析"),
            ModelInfo(id="sonar-reasoning", name="Sonar Reasoning", provider="Perplexity", default_base_url="https://api.perplexity.ai", context_window=127072, description="联网搜索 + 推理增强"),
        ],
    ),
    ProviderInfo(
        provider="MiniMax",
        display_name="MiniMax（海螺 AI）",
        default_base_url="https://api.minimax.chat/v1",
        auth_tip="从 platform.minimaxi.com 获取 API Key。使用新版 ChatCompletion V2（OpenAI 兼容格式）",
        models=[
            ModelInfo(id="abab6.5s-chat", name="ABAB 6.5S", provider="MiniMax", default_base_url="https://api.minimax.chat/v1", context_window=245760, description="MiniMax 旗舰超长上下文模型"),
            ModelInfo(id="abab5.5s-chat", name="ABAB 5.5S", provider="MiniMax", default_base_url="https://api.minimax.chat/v1", context_window=8192, description="轻量快速，适合高频对话"),
        ],
    ),
    ProviderInfo(
        provider="Ollama",
        display_name="Ollama（本地部署）",
        default_base_url="http://localhost:11434",
        api_type="openai-compatible",
        auth_tip="无需 API Key，确保 Ollama 已启动（ollama serve）",
        models=[
            ModelInfo(id="auto", name="自动检测已安装模型", provider="Ollama", default_base_url="http://localhost:11434", context_window=0, description="将自动从本地 Ollama 拉取模型列表"),
        ],
    ),
    ProviderInfo(
        provider="Local LLM",
        display_name="OpenAI 兼容代理（newapi / OneAPI / OpenRouter / Azure / 自部署）",
        default_base_url="http://localhost:8080",
        api_type="openai-compatible",
        auth_tip="填入任意 OpenAI 兼容服务的 Base URL 与 API Key——例如 newapi (https://your-newapi.com)、OneAPI、OpenRouter (https://openrouter.ai/api/v1)、Azure OpenAI、自部署 Ollama/vLLM 等。模型 ID 请按代理实际暴露的名字手填（如 deepseek-ai/deepseek-v3-pro）。系统会按 Base URL 自动识别已知供应商的格式；未知域名将走通用 /v1/chat/completions 端点。",
        models=[
            ModelInfo(id="auto", name="自动识别", provider="Local LLM", default_base_url="http://localhost:8080", context_window=0, description="按 Base URL 推断接口格式；模型 ID 请手填代理实际暴露的名字。"),
        ],
    ),
]


# Flat list for backward compat
SUPPORTED_PROVIDERS: list[ModelInfo] = [m for p in MODEL_CATALOG for m in p.models]


__all__ = ["ModelInfo", "ProviderInfo", "MODEL_CATALOG", "SUPPORTED_PROVIDERS"]
