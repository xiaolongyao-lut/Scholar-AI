# -*- coding: utf-8 -*-
"""
RAG Integration Entry Point (v1.0)
Role: 统一装配与调度入口 -- 读取配置, 初始化三个子系统, 分发 CLI 命令

职责边界:
    - 读取 config/rag_integration_config.yaml
    - 按配置初始化 RAGWorkflow / GraphRAGBridge / AutoRAGRunner
    - 支持三个 CLI 命令: ask / graphrag / autorag-generate
    - 不做业务推理, 只做装配和调度

使用方式:
    python rag_integration_entry.py ask --query "激光功率如何影响熔池中的氮传输?"
    python rag_integration_entry.py graphrag --query "laser power" [--level 1]
    python rag_integration_entry.py autorag-generate [--chunks-from <json_file>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Union, cast

from project_paths import CORE_ROOT
from text_utils import cjk_aware_tokenize

# ─── YAML 解析 (pyyaml 可选, 内置 fallback) ─────────────────────
try:
    import yaml
    HAS_YAML = True
except ImportError:
    yaml = None  # type: ignore[assignment]
    HAS_YAML = False

# ─── 模块级日志 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("rag_integration")

# ─── 默认配置路径 ────────────────────────────────────────────────
DEFAULT_CONFIG_PATH = str(CORE_ROOT / "config" / "rag_integration_config.yaml")
DEFAULT_LLM_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_LLM_MODEL = "ep-your-ark-endpoint"
DEFAULT_LLM_API_KEY_ENV = "ARK_API_KEY"
DEFAULT_EMBEDDING_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_EMBEDDING_API_KEY_ENV = "SILICONFLOW_API_KEY"
LEGACY_LLM_API_KEY_ENV_NAMES = ("SILICONFLOW_API_KEY",)
LEGACY_EMBEDDING_API_KEY_ENV_NAMES = ("SILICONFLOW_EMBEDDING_API_KEY",)
JsonValue = Union[None, bool, int, float, str, List["JsonValue"], Dict[str, "JsonValue"]]


class _RAGResultLike(Protocol):
    query: str
    focused_points: Sequence[str]
    memory_hits: Sequence[Mapping[str, object]]
    rag_evidence: Sequence[Mapping[str, object]]
    evidence_refs: Sequence[Mapping[str, object]]
    generated_answer: str
    confidence_score: float
    trace: Mapping[str, object]
    association_bundle: Optional[Mapping[str, object]]


def _json_safe(value: object) -> JsonValue:
    """Return a deterministic JSON-safe value for CLI machine output.

    Args:
        value: Arbitrary nested result data. Mapping keys are stringified and
            unsupported objects are converted to strings so CLI output never
            fails after a successful RAG run.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if isinstance(key, (str, int, float, bool))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _serialize_rag_result(result: _RAGResultLike) -> Dict[str, JsonValue]:
    """Serialize a RAG result for stable CLI/API handoff.

    Args:
        result: RAG workflow result with answer text, retrieved evidence, and
            machine-readable evidence references.

    Returns:
        A JSON-safe object that preserves citation provenance for downstream
        agents and UI consumers.
    """
    if not isinstance(result.query, str):
        raise TypeError("result.query must be a string")
    if not isinstance(result.generated_answer, str):
        raise TypeError("result.generated_answer must be a string")

    return {
        "query": result.query,
        "focused_points": _json_safe(list(result.focused_points)),
        "memory_hits": _json_safe(list(result.memory_hits)),
        "rag_evidence": _json_safe(list(result.rag_evidence)),
        "evidence_refs": _json_safe(list(result.evidence_refs)),
        "generated_answer": result.generated_answer,
        "confidence_score": _json_safe(float(result.confidence_score)),
        "trace": _json_safe(dict(result.trace)),
        "association_bundle": _json_safe(result.association_bundle),
    }


def _normalize_env_name(value: Any, default: str) -> str:
    """返回规范化后的环境变量名。"""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _resolve_from_env(
    preferred_env_name: str,
    legacy_env_names: Sequence[str] = (),
) -> Optional[str]:
    """按优先级从环境变量解析运行时值。"""
    env_names = [preferred_env_name, *legacy_env_names]
    for env_name in env_names:
        if not env_name:
            continue
        value = os.environ.get(env_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resolve_config_or_env(
    section: Dict[str, Any],
    field_name: str,
    env_name_field: str,
    default_env_name: str,
    legacy_env_names: Sequence[str] = (),
    default_value: Optional[str] = None,
) -> Optional[str]:
    """
    优先从环境变量读取配置，其次回退到 YAML 字段。

    Why:
        线上环境优先使用 Secrets，避免把运行时端点和模型强耦合到仓库
        文件；同时保留 YAML 作为本地默认值与回退值。
    """
    env_name = _normalize_env_name(section.get(env_name_field), default_env_name)
    env_value = _resolve_from_env(env_name, legacy_env_names)
    if env_value is not None:
        return env_value

    raw_value = section.get(field_name, default_value)
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        return raw_value.strip() or default_value
    return str(raw_value)


def _get_workflow_llm_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """解析聊天模型配置。"""
    workflow_cfg = cfg.get("workflow", {})
    return {
        "api_key": _resolve_from_env(
            _normalize_env_name(
                workflow_cfg.get("llm_api_key_env"),
                DEFAULT_LLM_API_KEY_ENV,
            ),
            LEGACY_LLM_API_KEY_ENV_NAMES,
        ),
        "base_url": _resolve_config_or_env(
            workflow_cfg,
            "llm_base_url",
            "llm_base_url_env",
            "ARK_BASE_URL",
            default_value=DEFAULT_LLM_BASE_URL,
        ) or DEFAULT_LLM_BASE_URL,
        "model": _resolve_config_or_env(
            workflow_cfg,
            "llm_model",
            "llm_model_env",
            "ARK_MODEL",
            default_value=DEFAULT_LLM_MODEL,
        ) or DEFAULT_LLM_MODEL,
        "enable_requests_fallback": workflow_cfg.get("enable_requests_fallback", True),
    }


def _get_embedding_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """解析 embedding 配置。"""
    embedding_cfg = cfg.get("embedding", {})
    return {
        "api_key": _resolve_from_env(
            _normalize_env_name(
                embedding_cfg.get("api_key_env"),
                DEFAULT_EMBEDDING_API_KEY_ENV,
            ),
            LEGACY_EMBEDDING_API_KEY_ENV_NAMES,
        ),
        "base_url": _resolve_config_or_env(
            embedding_cfg,
            "base_url",
            "base_url_env",
            "SILICONFLOW_EMBEDDING_BASE_URL",
            default_value=DEFAULT_EMBEDDING_BASE_URL,
        ) or DEFAULT_EMBEDDING_BASE_URL,
        "model": _resolve_config_or_env(
            embedding_cfg,
            "model",
            "model_env",
            "SILICONFLOW_EMBEDDING_MODEL",
            default_value=DEFAULT_EMBEDDING_MODEL,
        ) or DEFAULT_EMBEDDING_MODEL,
        "timeout": float(embedding_cfg.get("timeout", 60.0)),
        "batch_size": int(embedding_cfg.get("batch_size", 50)),
        "lazy_vectorize": bool(embedding_cfg.get("lazy_vectorize", True)),
    }


# ═══════════════════════════════════════════════════════════════════
# 配置加载
# ═══════════════════════════════════════════════════════════════════

def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    加载 YAML 配置文件。

    Args:
        config_path: 配置文件路径

    Returns:
        配置字典

    Raises:
        FileNotFoundError: 配置文件不存在
        ImportError: 缺少 pyyaml
    """
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. "
            f"Create it at {DEFAULT_CONFIG_PATH}"
        )

    if not HAS_YAML:
        raise ImportError(
            "pyyaml is required to parse config. Install via: pip install pyyaml"
        )

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError(f"Config file must contain a YAML mapping, got {type(config).__name__}")

    logger.info("Config loaded from: %s", config_path)
    return config


# ═══════════════════════════════════════════════════════════════════
# 子系统初始化工厂
# ═══════════════════════════════════════════════════════════════════

def _init_ragflow_adapter(cfg: Dict[str, Any]) -> Optional[Any]:
    """按配置初始化 RAGFlowAdapter, 失败时返回 None 并日志警告。"""
    ragflow_cfg = cfg.get("ragflow", {})
    if not ragflow_cfg.get("enabled", False):
        logger.info("RAGFlow adapter disabled by config")
        return None

    try:
        from layers.e_ragflow_retrieval_adapter import RAGFlowAdapter

        api_key = os.environ.get("RAGFLOW_API_KEY")
        if not api_key:
            logger.warning("RAGFLOW_API_KEY not set, RAGFlow adapter skipped")
            return None

        adapter = RAGFlowAdapter(
            api_key=api_key,
            base_url=ragflow_cfg.get("base_url", "https://localhost:9380"),
            verify_ssl=ragflow_cfg.get("verify_ssl", True),
            connect_timeout=ragflow_cfg.get("connect_timeout", 5),
            read_timeout=ragflow_cfg.get("read_timeout", 25),
            max_retries=ragflow_cfg.get("max_retries", 3)
        )
        logger.info("RAGFlowAdapter initialized (base_url=%s)", ragflow_cfg.get("base_url"))
        return adapter
    except Exception as exc:
        logger.warning("Failed to init RAGFlowAdapter: %s", exc)
        return None


def _init_graphrag_bridge(cfg: Dict[str, Any]) -> Optional[Any]:
    """按配置初始化 GraphRAGBridge, 失败时返回 None。"""
    graphrag_cfg = cfg.get("graphrag", {})
    if not graphrag_cfg.get("enabled", False):
        logger.info("GraphRAG bridge disabled by config")
        return None

    try:
        from layers.g_synthesis_graphrag_bridge import GraphRAGBridge

        index_path = graphrag_cfg.get("index_path", "./output/artifacts")
        bridge = GraphRAGBridge(index_path=index_path)
        logger.info("GraphRAGBridge initialized (index_path=%s)", index_path)
        return bridge
    except (FileNotFoundError, ImportError) as exc:
        logger.warning("Failed to init GraphRAGBridge: %s", exc)
        return None


def _init_autorag_runner(cfg: Dict[str, Any]) -> Optional[Any]:
    """按配置初始化 AutoRAGRunner, 失败时返回 None。"""
    autorag_cfg = cfg.get("autorag", {})
    if not autorag_cfg.get("enabled", False):
        logger.info("AutoRAG runner disabled by config")
        return None

    try:
        from layers.v_eval_autorag_runner import AutoRAGRunner

        runner = AutoRAGRunner(
            data_path=autorag_cfg.get("data_path", "./data"),
            output_dir=autorag_cfg.get("output_dir", "./autorag_out")
        )
        logger.info("AutoRAGRunner initialized")
        return runner
    except (ImportError, Exception) as exc:
        logger.warning("Failed to init AutoRAGRunner: %s", exc)
        return None


# ═══════════════════════════════════════════════════════════════════
# CLI 命令处理器
# ═══════════════════════════════════════════════════════════════════

async def cmd_ask(
    cfg: Dict[str, Any],
    query: str,
    dataset_ids: Optional[list] = None,
    include_association: bool = False,
    association_mode: str = "no_ai",
    project_id: Optional[str] = None,
    draft_id: Optional[str] = None,
    section_id: Optional[str] = None,
    json_output: bool = False,
) -> None:
    """
    ask 命令: 通过 RAGWorkflow 执行完整的 RAG 问答流程。
    """
    workflow_cfg = cfg.get("workflow", {})
    ragflow_cfg = cfg.get("ragflow", {})
    llm_settings = _get_workflow_llm_settings(cfg)

    # 初始化语义路由器 (简化: 若无 focus_points 则使用直通路由)
    router = _create_passthrough_router(cfg)

    # 初始化 RAGFlow 适配器
    adapter = _init_ragflow_adapter(cfg)

    # 导入并初始化工作流
    from main_rag_workflow import RAGWorkflow

    workflow = RAGWorkflow(
        semantic_router=router,
        ragflow_adapter=adapter,
        api_key=llm_settings["api_key"],
        base_url=llm_settings["base_url"],
        model=llm_settings["model"],
        enable_requests_fallback=llm_settings["enable_requests_fallback"]
    )

    try:
        # 确定 dataset_ids
        ids = dataset_ids or ragflow_cfg.get("dataset_ids", [])

        result = await workflow.ask_my_literature(
            user_query=query,
            top_k_points=workflow_cfg.get("top_k_points", 3),
            top_k_evidence=workflow_cfg.get("top_k_evidence", 5),
            dataset_ids=ids if ids else None,
            include_association=include_association,
            association_mode=association_mode,
            association_project_id=project_id,
            association_draft_id=draft_id,
            association_section_id=section_id,
        )

        # 输出结果
        if json_output:
            print(json.dumps(_serialize_rag_result(result), ensure_ascii=False, indent=2))
            return

        print("\n" + "=" * 60)
        print(f"Query: {result.query}")
        print(f"Focus Points: {result.focused_points}")
        print(f"Memory Hits: {len(result.memory_hits)}")
        print(f"Evidence Count: {len(result.rag_evidence)}")
        print(f"Confidence: {result.confidence_score:.2f}")
        print("-" * 60)
        print(f"Answer:\n{result.generated_answer}")
        if result.association_bundle:
            print("-" * 60)
            print("Association:")
            print(json.dumps(result.association_bundle, indent=2, ensure_ascii=False))
        print("=" * 60)

    finally:
        await workflow.close()


def cmd_graphrag(cfg: Dict[str, Any], query: str, level: int = 1) -> None:
    """
    graphrag 命令: 查询 GraphRAG 社区图谱。
    """
    bridge = _init_graphrag_bridge(cfg)
    if bridge is None:
        print("[ERROR] GraphRAG bridge is not available. Check config and index_path.")
        sys.exit(1)

    graphrag_cfg = cfg.get("graphrag", {})
    target_level = level if level is not None else graphrag_cfg.get("default_community_level", 1)

    # 获取社区报告
    communities = bridge.get_global_communities(level=target_level)
    print(f"\n[GraphRAG] Communities at level {target_level}: {len(communities)}")

    # 实体关联查询
    if query:
        associations = bridge.get_entity_association(query)
        print(f"[GraphRAG] Entity match for '{query}':")
        print(f"  Entities:    {len(associations['matched_entities'])}")
        print(f"  Communities: {len(associations['matched_communities'])}")
        print(f"  Reports:     {len(associations['matched_reports'])}")

        # 输出详细结果
        if associations["matched_reports"]:
            print("\n--- Matched Reports ---")
            for rpt in associations["matched_reports"][:3]:
                title = rpt.get("title", "N/A")
                summary = str(rpt.get("summary", ""))[:200]
                print(f"  [{title}] {summary}")


def cmd_autorag_generate(cfg: Dict[str, Any], chunks_from: Optional[str] = None) -> None:
    """
    autorag-generate 命令: 生成 AutoRAG 评测数据集。
    """
    runner = _init_autorag_runner(cfg)
    if runner is None:
        print("[ERROR] AutoRAG runner is not available. Check config and dependencies.")
        sys.exit(1)

    chunks = None
    if chunks_from:
        chunks_path = Path(chunks_from)
        if not chunks_path.is_file():
            print(f"[ERROR] Chunks file not found: {chunks_from}")
            sys.exit(1)
        with open(chunks_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                chunks = data
            elif isinstance(data, dict) and "chunks" in data:
                chunks = data["chunks"]
            else:
                print("[ERROR] Chunks file must be a JSON list or dict with 'chunks' key")
                sys.exit(1)
        print(f"[AutoRAG] Loaded {len(chunks)} chunks from {chunks_from}")

    qa_path = runner.generate_eval_set(chunks=chunks)
    print(f"\n[AutoRAG] Eval set generated:")
    print(f"  QA:       {qa_path}")
    print(f"  Corpus:   {runner.corpus_path}")
    print(f"  Manifest: {runner.manifest_path}")


# ═══════════════════════════════════════════════════════════════════
# 辅助工具
# ═══════════════════════════════════════════════════════════════════

def _create_passthrough_router(cfg: Optional[Dict[str, Any]] = None) -> Any:
    """
    创建直通路由器 (当 focus_points.json 不可用时的兜底)。
    直接将查询关键词作为 focus points 返回。
    """
    try:
        from layers.semantic_router import SemanticRouter
        embedding_settings = _get_embedding_settings(cfg or {})
        api_key = embedding_settings["api_key"]
        if api_key and Path("focus_points.json").exists():
            return SemanticRouter(
                api_key=api_key,
                focus_points_path="focus_points.json",
                base_url=embedding_settings["base_url"],
                embedding_model=embedding_settings["model"],
                timeout=embedding_settings["timeout"],
                batch_size=embedding_settings["batch_size"],
                lazy_vectorize=embedding_settings["lazy_vectorize"],
            )
    except Exception as exc:
        logger.debug("SemanticRouter not available, using passthrough: %s", exc)

    # 返回一个简单的 passthrough mock
    class PassthroughRouter:
        async def route_query(self, query: str, top_k: int = 3) -> list:
            # 简单分词作为 focus points
            words = [word for word in cjk_aware_tokenize(query) if len(word.strip()) > 1]
            return words[:top_k] if words else [query]

    return PassthroughRouter()


# ═══════════════════════════════════════════════════════════════════
# CLI 主入口
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RAG Integration Entry Point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rag_integration_entry.py ask --query "..."
  python rag_integration_entry.py graphrag --query "laser power" --level 1
  python rag_integration_entry.py autorag-generate --chunks-from data.json
        """
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH,
        help=f"Config file path (default: {DEFAULT_CONFIG_PATH})"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── ask 子命令 ──
    ask_parser = subparsers.add_parser("ask", help="RAG Q&A workflow")
    ask_parser.add_argument("--query", required=True, help="User query")
    ask_parser.add_argument("--dataset-ids", nargs="*", help="RAGFlow dataset IDs")
    ask_parser.add_argument("--with-association", action="store_true", help="Build associative writing bundle")
    ask_parser.add_argument("--association-mode", choices=["no_ai", "ai"], default="no_ai", help="Association bundle mode")
    ask_parser.add_argument("--project-id", help="Existing writing project ID for association context")
    ask_parser.add_argument("--draft-id", help="Existing draft ID for association context")
    ask_parser.add_argument("--section-id", help="Existing section ID for association context")
    ask_parser.add_argument("--json-output", action="store_true", help="Print full machine-readable RAG result JSON")

    # ── graphrag 子命令 ──
    graphrag_parser = subparsers.add_parser("graphrag", help="GraphRAG community query")
    graphrag_parser.add_argument("--query", required=True, help="Entity query")
    graphrag_parser.add_argument("--level", type=int, default=1, help="Community level")

    # ── autorag-generate 子命令 ──
    autorag_parser = subparsers.add_parser("autorag-generate", help="Generate AutoRAG eval set")
    autorag_parser.add_argument("--chunks-from", help="JSON file with chunks data")

    args = parser.parse_args()

    # 加载配置
    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ImportError, ValueError) as exc:
        print(f"[ERROR] Config load failed: {exc}")
        sys.exit(1)

    # 分发命令
    if args.command == "ask":
        asyncio.run(
            cmd_ask(
                cfg,
                args.query,
                args.dataset_ids,
                include_association=args.with_association,
                association_mode=args.association_mode,
                project_id=args.project_id,
                draft_id=args.draft_id,
                section_id=args.section_id,
                json_output=cast(bool, args.json_output),
            )
        )

    elif args.command == "graphrag":
        cmd_graphrag(cfg, args.query, args.level)

    elif args.command == "autorag-generate":
        cmd_autorag_generate(cfg, args.chunks_from)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
