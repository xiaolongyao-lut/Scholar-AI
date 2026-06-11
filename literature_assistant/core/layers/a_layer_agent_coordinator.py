from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

logger = logging.getLogger("A_Layer_Agent")

ARCHITECTURE_LAYERS = {
    'constraints': '约束器：只定义目标、固定主线、命名规则、输出契约与硬规则，不直接调用工具。',
    'router': '调度器：只把用户需求和AI判断翻译为标准mode，先服从约束，再调工具。',
    'tools': '工具集：只执行extract/bind/select/pack/register/crop/build/deliver/word/fullchain。',
    'validators': '检查器：专门检查约束、调度、工具之间是否冲突，并检查输出契约。',
}

OPEN_FOCUS_STOPWORDS = {
    '提取', '抽取', '处理', '整理', '分析', '检查', '测试', '先', '正式', '文献', '文章', '论文',
    '根据', '围绕', '关注', '聚焦', '从', '针对', '角度', '方面', '以及', '还有', '先看', '先做',
    '材料', '主线', '不要', '偏离', '研究', '结果', '问题', '任务', '这篇', '那篇', '当前', '完整',
    'fullchain', 'extract', 'bind', 'select', 'pack', 'register', 'crop', 'build', 'deliver', 'word',
    'check', 'emit', '控制', 'ai', 'AI', '智能', '交叉领域'
}
OPEN_FOCUS_TRIGGER_RE = re.compile(r'(?:围绕|关注|聚焦|针对|从|面向|关于)([^，。；;,\.\n]{2,48})')
OPEN_FOCUS_TOKEN_RE = re.compile(r'[A-Za-z][A-Za-z0-9_\-]{2,24}|[一-鿿]{2,12}')


def infer_open_focus_points(command: str, explicit_goal: str = '', known_focus_keywords: set[str] | None = None) -> list[str]:
    known_focus_keywords = known_focus_keywords or set()
    text = f"{command or ''} {explicit_goal or ''}".strip()
    if not text:
        return []
    phrases = OPEN_FOCUS_TRIGGER_RE.findall(text) or [text]
    candidates: list[str] = []
    generic_fragments = [
        '根据', '围绕', '关注', '聚焦', '针对', '从', '面向', '关于', '先提取', '提取', '抽取',
        '处理', '整理', '分析', '检查', '测试', '生成', '并生成', '输出', '构建', '运行', '跑',
        '正式文献', '这篇', '文献', '文章', '论文',
        '构建目标导向写作材料包', '原文', '交付包', '验收Word', '验收word', '写作整合稿', '完整材料包', '生成验收Word', '生成验收word',
        '最小包', '云盘包', '入云盘', '可入云盘', '一路做到', '从提取一路做到', '整条跑完', '跑完整条'
    ]
    for phrase in phrases:
        clean = phrase
        for frag in generic_fragments:
            clean = clean.replace(frag, ' ')
        clean = re.sub(r"[“”\"'()（）\[\]{}<>]", ' ', clean)
        clean = re.sub(r'[、，,；;。./]+', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        for token in OPEN_FOCUS_TOKEN_RE.findall(clean):
            t = token.strip()
            t = re.sub(r'^[与和及并]+', '', t)
            if not t or t in OPEN_FOCUS_STOPWORDS:
                continue
            if any(kw in t for kw in known_focus_keywords if len(kw) >= 2):
                continue
            t_low = t.lower()
            if any(sw in t for sw in ('提取', '文献', '材料包', '交付包', '这篇', '正式', '当前', '验收', 'word', 'Word', '原文', '生成', '输出', '构建', '运行')):
                continue
            if t_low in {'scientific', 'machine', 'learning', 'digital', 'twin', 'ai', 'ml', 'am'}:
                continue
            if t in {'增材制造', '材料主问题', '原位监测'}:
                continue
            if t.startswith('并') or t.endswith('生成') or t.endswith('给我') or t.endswith('云盘'):
                continue
            if t in {'先把', '整条', '最后给我', '最后给我云盘'}:
                continue
            if len(t) <= 1:
                continue
            candidates.append(t)
    dedup: list[str] = []
    for item in candidates:
        if item not in dedup:
            dedup.append(item)
    return dedup[:6]


# ============================================================
# AIEngine: AI 自由调度引擎
# ============================================================

class ToolSpec:
    """工具注册描述"""
    __slots__ = ("name", "fn", "description", "param_hints")

    def __init__(self, name: str, fn: Callable[..., Any], description: str,
                 param_hints: dict[str, str] | None = None):
        self.name = name
        self.fn = fn
        self.description = description
        self.param_hints = param_hints or {}


class AgentResponse:
    """AI 调度执行结果"""
    __slots__ = ("query", "tool_calls", "results", "summary")

    def __init__(self, query: str):
        self.query = query
        self.tool_calls: list[dict[str, Any]] = []
        self.results: list[Any] = []
        self.summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "tool_calls": self.tool_calls,
            "results": [
                r if isinstance(r, (dict, list, str, int, float, bool, type(None)))
                else str(r)
                for r in self.results
            ],
            "summary": self.summary,
        }


class AIEngine:
    """AI 调度引擎：根据用户意图动态选择调用工具组合。

    支持两种模式：
    - LLM 模式：将工具注册表发给 LLM，由 LLM 决定调用哪些工具
    - 降级模式（无 LLM）：基于关键词匹配自动选择工具
    """

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}
        self._llm_adapter = None

        # 尝试加载 LLM
        try:
            from layers.g_layer_academic_generator import AIAdapter
            adapter = AIAdapter()
            if adapter.available:
                self._llm_adapter = adapter
        except Exception:
            pass

    @property
    def has_llm(self) -> bool:
        return self._llm_adapter is not None

    def register_tool(self, name: str, fn: Callable[..., Any], description: str,
                      param_hints: dict[str, str] | None = None):
        """注册一个可被 AI 调度的工具函数"""
        self._tools[name] = ToolSpec(name, fn, description, param_hints)

    def get_tool_descriptions(self) -> list[dict[str, str]]:
        """返回所有已注册工具的描述（供 LLM function-calling）"""
        return [
            {"name": t.name, "description": t.description, "parameters": t.param_hints}
            for t in self._tools.values()
        ]

    def dispatch(self, user_query: str) -> AgentResponse:
        """根据用户意图调度工具。

        LLM 模式: 将 query + tool descriptions 发送给 LLM → LLM 选择工具 → 执行
        降级模式: 关键词匹配 → 执行最相关的工具
        """
        response = AgentResponse(query=user_query)

        if self._llm_adapter and hasattr(self._llm_adapter, "chat"):
            return self._dispatch_with_llm(user_query, response)
        return self._dispatch_keyword(user_query, response)

    def _dispatch_keyword(self, query: str, response: AgentResponse) -> AgentResponse:
        """降级模式：基于关键词匹配选择工具"""
        query_lower = query.lower()

        # 关键词 → 工具名映射
        keyword_map = {
            "search_memory": ["记忆", "联想", "回忆", "memory", "recall", "association"],
            "generate_inspiration": ["启发", "灵感", "创作点", "思路", "inspire", "spark", "idea"],
            "find_causal_chains": ["因果", "原因", "导致", "causal", "cause", "effect", "chain"],
            "detect_conflicts": ["冲突", "矛盾", "对比", "conflict", "contradiction", "compare"],
            "retrieve_evidence": ["证据", "检索", "查找", "evidence", "search", "retrieve"],
            "draft_continuation": ["续写", "扩展", "继续", "continue", "expand", "draft", "写作"],
        }

        matched_tools = []
        for tool_name, keywords in keyword_map.items():
            if tool_name in self._tools:
                score = sum(1 for kw in keywords if kw in query_lower)
                if score > 0:
                    matched_tools.append((tool_name, score))

        if not matched_tools:
            # 默认调用启发点生成或记忆搜索
            for fallback in ("generate_inspiration", "search_memory"):
                if fallback in self._tools:
                    matched_tools.append((fallback, 1))
                    break

        matched_tools.sort(key=lambda x: x[1], reverse=True)

        for tool_name, _ in matched_tools[:3]:
            tool = self._tools[tool_name]
            call_record = {"tool": tool_name, "input": {"query": query}}
            try:
                result = tool.fn(query=query)
                call_record["status"] = "success"
                response.results.append(result)
            except Exception as e:
                call_record["status"] = "error"
                call_record["error"] = str(e)
                logger.warning("工具 %s 执行失败: %s", tool_name, e)
            response.tool_calls.append(call_record)

        response.summary = f"降级模式: 调用了 {len(response.tool_calls)} 个工具"
        return response

    def _dispatch_with_llm(self, query: str, response: AgentResponse) -> AgentResponse:
        """LLM 模式：将工具描述发给 LLM，由 LLM 决定调用策略"""
        tool_desc_text = "\n".join(
            f"- {t.name}: {t.description}" for t in self._tools.values()
        )
        system_prompt = (
            "你是一个文献分析助手的调度引擎。根据用户的查询意图，选择最合适的工具组合。\n"
            f"可用工具:\n{tool_desc_text}\n\n"
            "请以 JSON 格式回复你的工具调用计划:\n"
            '[{"tool": "tool_name", "params": {"query": "..."}}]\n'
            "只返回 JSON 数组，不要其他内容。"
        )

        try:
            llm_response = self._llm_adapter.chat(system_prompt, query)
            # 尝试解析 LLM 返回的工具调用计划
            plan = json.loads(llm_response)
            if isinstance(plan, list):
                for step in plan[:5]:
                    tool_name = step.get("tool", "")
                    params = step.get("params", {})
                    if tool_name in self._tools:
                        tool = self._tools[tool_name]
                        call_record = {"tool": tool_name, "input": params}
                        try:
                            result = tool.fn(**params)
                            call_record["status"] = "success"
                            response.results.append(result)
                        except Exception as e:
                            call_record["status"] = "error"
                            call_record["error"] = str(e)
                        response.tool_calls.append(call_record)
            response.summary = f"LLM 模式: 调用了 {len(response.tool_calls)} 个工具"
        except json.JSONDecodeError as e:
            logger.warning("LLM 输出 JSON 解析失败,降级到关键词模式: %s", e)
            return self._dispatch_keyword(query, response)
        except Exception as e:
            logger.warning("LLM 调度异常,降级到关键词模式: %s", e)
            return self._dispatch_keyword(query, response)

        return response


def create_default_engine(
    mempalace=None,
    inspiration_engine=None,
    causal_engine=None,
    conflict_detector=None,
    retriever=None,
) -> AIEngine:
    """创建并注册默认工具集的 AIEngine 实例。"""
    engine = AIEngine()

    if mempalace and hasattr(mempalace, "search"):
        engine.register_tool(
            "search_memory",
            lambda query, limit=5: mempalace.search(query, wing="literature", limit=limit),
            "搜索文献记忆库，返回相关知识碎片",
            {"query": "str", "limit": "int"},
        )

    if inspiration_engine and hasattr(inspiration_engine, "generate_sparks"):
        engine.register_tool(
            "generate_inspiration",
            lambda query, limit=10: [s.to_dict() for s in inspiration_engine.generate_sparks(query, limit)],
            "生成启发点/创作灵感，基于跨论文联想",
            {"query": "str", "limit": "int"},
        )

    if causal_engine and hasattr(causal_engine, "extract_chains"):
        def find_causal(query, **_kw):
            # 简单查找：在已有 DAG 中搜索包含 query 关键词的链路
            return {"message": "因果链查询需要先加载 DAG 数据", "query": query}
        engine.register_tool(
            "find_causal_chains",
            find_causal,
            "查找某个实体/概念相关的因果链",
            {"query": "str"},
        )

    if conflict_detector and hasattr(conflict_detector, "detect_conflicts"):
        engine.register_tool(
            "detect_conflicts",
            lambda query, **_kw: conflict_detector.detect_conflicts(),
            "检测文献中同一参数的矛盾结论",
            {"query": "str"},
        )

    if retriever and hasattr(retriever, "hybrid_search"):
        engine.register_tool(
            "retrieve_evidence",
            lambda query, **_kw: retriever.hybrid_search(None, query=query, top_k=10),
            "为某个声明检索支撑证据",
            {"query": "str"},
        )

    return engine
