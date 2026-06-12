"""Generic feature flag registry with override persistence + env fallback.

Resolution priority for each registered flag:
  1. ``runtime_state/feature_flags_override.json`` (UI-writable via API)
  2. Environment variable (legacy / dev override)
  3. Registered default

The registry (``FEATURE_FLAGS``) is the single source of truth for which flags
exist; arbitrary keys in the override file are ignored. Add new flags by
appending a ``FeatureFlagSpec`` to ``FEATURE_FLAGS``.

Atomic writes (tempfile + ``os.replace``) mirror ``model_config_store`` so a
crash mid-write cannot corrupt the override document.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from _atomic_io import CrossProcessFileLock
from project_paths import runtime_state_path


_TRUTHY_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on", "y"})


def _truthy(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in _TRUTHY_VALUES


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class FeatureFlagSpec:
    """Static metadata for a feature flag exposed to the Settings UI."""

    name: str
    default: bool
    env_var: Optional[str]
    label: str
    description: str


FEATURE_FLAGS: dict[str, FeatureFlagSpec] = {
    "pdf_parser_marker": FeatureFlagSpec(
        name="pdf_parser_marker",
        default=False,
        env_var=None,  # Coexist with the LITASSIST_PDF_PARSER string env var
                       # in get_pdf_backend() — either path opts into marker.
        label="PDF 结构化解析(marker)",
        description=(
            "用 marker-pdf 替代默认 PyMuPDF 解析新上传的 PDF;能识别标题层级、表格、"
            "公式与图片,RAG 检索质量更好。需先 `pip install marker-pdf`(~2GB 含模型);"
            "首次解析每篇约 5-15 分钟。已入库的旧 PDF 不会自动重做,可在项目工作台点 "
            "「重新解析以获取结构化索引」按 marker 重建。关闭后新上传 PDF 走 PyMuPDF "
            "默认链路,旧结构化数据保留。"
        ),
    ),
    "rag_chunk_type_weighting": FeatureFlagSpec(
        name="rag_chunk_type_weighting",
        default=False,
        env_var="RAG_CHUNK_TYPE_WEIGHTING_ENABLED",
        label="RAG 按 chunk 类型加权(实验)",
        description=(
            "检索时按 chunk_type(narrative / table / formula / heading / "
            "figure_caption / list / code 等)对得分加权,让表格 / 公式 / 标题命中"
            "更易进 top-k。需要 chunks 已带 chunk_type 元数据(marker 重新解析的"
            "项目自带,纯 PyMuPDF chunks 也有最基础的类型)。当前权重值为基线 1.0,"
            "等真实 RAG 评测后再校准 — 启用本开关只激活加权代码路径,不一定立刻提升答案质量。"
        ),
    ),
    "tolf_context": FeatureFlagSpec(
        name="tolf_context",
        default=False,
        env_var="INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED",
        label="TOLF 目标导向检索",
        description=(
            "把问题拆成多面查询，在文献图上扩散，并按硬证据筛选结果。"
            "比默认 RAG 更慢，但找间接证据、归因清晰、抗弱化措辞。"
            "适合综述、找数据、深度调研。同一问题分别开/关跑一次可直观对比。"
        ),
    ),
    "tolf_fusion_mode": FeatureFlagSpec(
        name="tolf_fusion_mode",
        default=False,
        env_var="INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED",
        label="TOLF 融合 RAG (RRF)",
        description=(
            "需要同时打开「TOLF 目标导向检索」。开启后 TOLF 不再替代 RAG,"
            "改为与 RAG 候选池通过 Reciprocal Rank Fusion 合并: TOLF 给目标侧候选,"
            "RAG 给词面侧候选, 各自独立排序后用 RRF 融合 (k=60), 再截到 max_chunks。"
            "默认 off, 保持历史 fallback 行为不变; 适合调研型问题想要更广覆盖时打开。"
        ),
    ),
    "hybrid_retrieval": FeatureFlagSpec(
        name="hybrid_retrieval",
        default=False,
        env_var="INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED",
        label="Chat 真 hybrid 检索 (BM25+dense+rerank)",
        description=(
            "开启后 chat 路径的 RAG 召回从「关键词重叠」升级为 ContextAwareRetriever 真"
            " hybrid_search: BM25 词面分 + chunk.embedding 余弦 dense 分 +(若 rerank 服务"
            "可用)再过 reranker_client。需要项目 chunk 已有 embedding(scripts/"
            "embedding_backfill.py 回填), 没 embedding 的 chunk 会自动退化为 BM25-only,"
            "因此对未回填项目也安全; 与 tolf_fusion_mode 组合时, RAG 这一侧候选改走"
            "hybrid_search 的真分数。默认 off, 实验稳定后再考虑切换默认值。"
        ),
    ),
    "rag_structured_sibling_inclusion": FeatureFlagSpec(
        name="rag_structured_sibling_inclusion",
        default=False,
        env_var="RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED",
        label="同 section 结构化邻居补全",
        description=(
            "答完最终 top-K 后, 看 narrative 命中的 chunk 所在 section_path / page,"
            "把同 section 的 table / formula / figure_caption 邻居自动补进上下文。"
            "解决 A15 (chunk-type 加权) 把表格送进 rerank 候选池后, 仍可能被 reranker"
            "压在 narrative summary 下的痛点 — 比如答案里说\"Table 2 给出 creep 速率\","
            "Table 2 chunk 本身却没进 top-K。默认 off, 每个 query 最多补 2 个邻居,"
            "且只在 narrative chunk 已 earn 进 top-K 时才触发, 不抢已有 rerank 排名。"
        ),
    ),
    "local_rerank": FeatureFlagSpec(
        name="local_rerank",
        default=True,
        env_var="ENABLE_LOCAL_RERANK",
        label="主线 Rerank(API 优先)",
        description=(
            "语义路由把候选证据交给配置的 rerank 服务(SiliconFlow / DashScope / "
            "或本地 loopback 服务等)重排。API 不可用时按 hybrid_score 静态排序兜底。"
            "本开关名义上含「本地」是历史遗留 — 真正的本地 rerank 是「本地 loopback "
            "Rerank 服务(实验)」开关 + Settings 里把 RERANK_BASE_URL 指向 "
            "http://127.0.0.1:<port>。"
        ),
    ),
    "rag_local_cross_encoder_rerank": FeatureFlagSpec(
        name="rag_local_cross_encoder_rerank",
        default=False,
        env_var="RAG_LOCAL_CROSS_ENCODER_RERANK_ENABLED",
        label="本地 loopback Rerank 服务(实验)",
        description=(
            "云端 rerank API 失败(或 DNS 被代理 fake-IP 拦截)时,fallback 到本机 "
            "loopback rerank HTTP 服务(默认 http://127.0.0.1:7997/rerank,"
            "由 local_rerank_server.py 起,加载 BAAI/bge-reranker-v2-m3)。"
            "服务进程独立于主后端,不在 FastAPI 主进程吃模型权重。"
            "权重需先下载到 ~/.cache/huggingface/hub(约 2GB);服务未启动或权重缺时"
            "本开关自动失效,走 hybrid_score 静态排序兜底。"
        ),
    ),
    "analysis_chain_rag": FeatureFlagSpec(
        name="analysis_chain_rag",
        default=True,
        env_var="ANALYSIS_CHAIN_RAG_ENABLED",
        label="RAG 答问附推理过程",
        description=(
            "主线答问在返回答案的同时附带结构化推理过程（观察/机制/证据/边界/反证/下一步）。"
            "默认走确定性生成，不增加模型调用；如需让 LLM 写完整推理链，再打开「LLM 生成」开关。"
        ),
    ),
    "analysis_chain_rag_llm": FeatureFlagSpec(
        name="analysis_chain_rag_llm",
        default=False,
        env_var="ANALYSIS_CHAIN_RAG_LLM_ENABLED",
        label="RAG 推理过程用 LLM 生成",
        description=(
            "在「RAG 答问附推理过程」基础上，用 LLM 生成完整推理链（每次答问多 1 次 LLM 调用）。"
            "失败时自动回退到确定性生成，不会让答问失败。"
        ),
    ),
    "analysis_chain_discussion": FeatureFlagSpec(
        name="analysis_chain_discussion",
        default=True,
        env_var="ANALYSIS_CHAIN_DISCUSSION_ENABLED",
        label="多智能体讨论附推理过程",
        description=(
            "讨论中每个智能体发言时携带证据化推理摘要；反对方偏重反证，审稿人偏重边界，主持人偏重下一步。"
            "可在讨论面板点击单个智能体回答，逐个展开该角色的思路。"
        ),
    ),
    "analysis_chain_carryover": FeatureFlagSpec(
        name="analysis_chain_carryover",
        default=False,
        env_var="ANALYSIS_CHAIN_CARRYOVER_ENABLED",
        label="AI 接住上一步推理",
        description=(
            "下一个智能体或下一轮对话能拿到上一步的推理链作为参考，AI 不从零想，可承接前一步结论。"
            "当上下文预算紧张时会优先丢弃这部分参考，不影响主流程。"
        ),
    ),
    "analysis_chain_ui": FeatureFlagSpec(
        name="analysis_chain_ui",
        default=True,
        env_var="ANALYSIS_CHAIN_UI_ENABLED",
        label="推理过程展开按钮",
        description=(
            "答案带有推理过程时，界面提供「展开」入口并默认保持收起。"
            "关闭时不影响答问能力，只隐藏界面入口。"
        ),
    ),
    "discussion_streaming": FeatureFlagSpec(
        name="discussion_streaming",
        default=True,
        env_var="DISCUSSION_STREAMING_ENABLED",
        label="多智能体讨论流式输出",
        description=(
            "讨论运行时逐个显示智能体完成进度，长讨论不用等全部结束才看到结果。"
            "关闭后仍可完成讨论，只是不再显示实时进度。"
        ),
    ),
    "inspector_embed_unified": FeatureFlagSpec(
        name="inspector_embed_unified",
        default=True,
        env_var="INSPECTOR_EMBED_UNIFIED_ENABLED",
        label="工作台 Inspector 嵌入完整功能",
        description=(
            "在研究工作台右侧 Inspector 直接嵌入「智能研读」和「多智能体讨论」完整组件，"
            "作为默认主线入口使用。关闭后才回退为跳转入口。"
        ),
    ),
    "wiki": FeatureFlagSpec(
        name="wiki",
        default=False,
        env_var="LITERATURE_ASSISTANT_WIKI_ENABLED",
        label="Wiki 知识沉淀",
        description=(
            "开启后可使用 Wiki 工作台、页面检索、编译和审阅队列，把项目资料沉淀为可回看的本地知识页。"
            "关闭时保留已有页面和索引文件，只隐藏/阻止 Wiki API 写入与查询入口。"
        ),
    ),
    "evolution_candidate_capture": FeatureFlagSpec(
        name="evolution_candidate_capture",
        default=True,
        env_var="LITERATURE_ASSISTANT_EVOLUTION_CAPTURE_ENABLED",
        label="经验候选收纳",
        description=(
            "开启后，智能研读、讨论、写作任务、Skill 和 MCP 工具运行完成时，"
            "会把可复用经验放入复审队列，等待人工确认。"
        ),
    ),
    "evolution_review_ui": FeatureFlagSpec(
        name="evolution_review_ui",
        default=False,
        env_var="LITERATURE_ASSISTANT_EVOLUTION_REVIEW_UI_ENABLED",
        label="学到的经验复审入口",
        description=(
            "开启后显示“学到的经验”页面，用于查看、保存、忽略和撤销经验候选。"
            "关闭时不删除已有候选。"
        ),
    ),
    "evolution_promotion": FeatureFlagSpec(
        name="evolution_promotion",
        default=False,
        env_var="LITERATURE_ASSISTANT_EVOLUTION_PROMOTION_ENABLED",
        label="经验应用到长期记忆",
        description=(
            "开启后，已保存的经验可以继续应用到长期记忆或 Skill 草稿。"
            "关闭时仍可复审候选，但不会写入长期记忆。"
        ),
    ),
}


_OVERRIDE_PATH: Path = runtime_state_path("feature_flags_override.json")
_LOCK = threading.Lock()


def _override_lock_path() -> Path:
    return _OVERRIDE_PATH.with_suffix(f"{_OVERRIDE_PATH.suffix}.lock")


def _read_overrides() -> dict[str, bool]:
    try:
        with open(_OVERRIDE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    flags = data.get("flags")
    if not isinstance(flags, dict):
        return {}
    return {k: bool(v) for k, v in flags.items() if isinstance(k, str)}


def _write_overrides_atomic(overrides: dict[str, bool]) -> None:
    if not overrides:
        try:
            _OVERRIDE_PATH.unlink()
        except FileNotFoundError:
            pass
        return
    payload = {"flags": overrides, "updated_at": _now_iso()}
    _OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix="feature_flags_override_",
        suffix=".json.tmp",
        dir=str(_OVERRIDE_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, _OVERRIDE_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _resolve(spec: FeatureFlagSpec, overrides: dict[str, bool]) -> tuple[bool, str]:
    if spec.name in overrides:
        return bool(overrides[spec.name]), "override"
    if spec.env_var:
        env_val = os.getenv(spec.env_var)
        if env_val is not None and env_val.strip():
            return _truthy(env_val), "env"
    return spec.default, "default"


def is_enabled(name: str) -> bool:
    """Resolve a feature flag. Unknown flags return False."""
    spec = FEATURE_FLAGS.get(name)
    if spec is None:
        return False
    with _LOCK, CrossProcessFileLock(_override_lock_path()):
        current, _ = _resolve(spec, _read_overrides())
    return current


def list_flags() -> list[dict[str, Any]]:
    """Return every registered flag with metadata + currently resolved value."""
    with _LOCK, CrossProcessFileLock(_override_lock_path()):
        overrides = _read_overrides()
    out: list[dict[str, Any]] = []
    for spec in FEATURE_FLAGS.values():
        current, source = _resolve(spec, overrides)
        out.append(
            {
                "name": spec.name,
                "label": spec.label,
                "description": spec.description,
                "default": spec.default,
                "env_var": spec.env_var,
                "current": current,
                "source": source,
            }
        )
    return out


def set_flag(name: str, enabled: bool) -> dict[str, Any]:
    """Persist an override for a registered flag. Returns the resolved entry."""
    if name not in FEATURE_FLAGS:
        raise KeyError(f"unknown feature flag: {name}")
    with _LOCK, CrossProcessFileLock(_override_lock_path()):
        overrides = _read_overrides()
        overrides[name] = bool(enabled)
        _write_overrides_atomic(overrides)
    return next(f for f in list_flags() if f["name"] == name)


__all__ = [
    "FeatureFlagSpec",
    "FEATURE_FLAGS",
    "is_enabled",
    "list_flags",
    "set_flag",
]
