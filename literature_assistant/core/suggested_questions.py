# -*- coding: utf-8 -*-
"""Deterministic, model-free suggested-question generation for SmartRead.

Backend port of the frontend ``suggestedQuestions.ts`` heuristic. A keyword
classifier picks a domain (review / welding / mechanics / method / materials /
application / general) from the material metadata plus its chunk text, then
returns a fixed set of paper-aware question templates. No model call is made.

The backend uses a much larger slice of chunk text than the frontend
(first-chunks only), so classification is more representative of the whole
document. Output shape mirrors the frontend ``SuggestedQuestion``:
``{"id", "label", "question", "kind"}``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

QuestionKind = str
SuggestedQuestion = dict[str, str]

QUESTION_LIMIT = 5
# Backend can afford far more context than the frontend's 18k char window.
CONTEXT_CHAR_LIMIT = 40_000
MAX_CHUNKS = 80

_REVIEW_KEYWORDS: list[str] = [
    "review", "survey", "overview", "progress", "state of the art",
    "recent advances", "综述", "进展", "研究现状", "发展现状",
]

# Order matters: detection prefers earlier rules on ties (welding > mechanics >
# method > materials > application), matching the frontend behaviour.
_KEYWORD_RULES: list[tuple[QuestionKind, list[str]]] = [
    ("welding", [
        "weld", "welding", "laser welding", "friction stir", "arc welding",
        "tig", "mig", "熔焊", "焊接", "激光焊", "搅拌摩擦焊", "电弧焊", "接头", "热影响区",
    ]),
    ("mechanics", [
        "fatigue", "static load", "dynamic load", "cyclic load", "impact",
        "fracture", "crack", "stress", "strain", "creep", "tension", "compression",
        "疲劳", "静载", "动载", "循环载荷", "冲击", "断裂", "裂纹", "应力", "应变", "拉伸", "压缩",
    ]),
    ("method", [
        "model", "algorithm", "simulation", "finite element", "machine learning",
        "neural network", "optimization",
        "模型", "算法", "仿真", "有限元", "机器学习", "神经网络", "优化",
    ]),
    ("materials", [
        "alloy", "steel", "aluminum", "titanium", "composite", "microstructure",
        "grain", "phase", "hardness",
        "材料", "合金", "钢", "铝", "钛", "复合材料", "显微组织", "晶粒", "相变", "硬度",
    ]),
    ("application", [
        "case study", "industrial", "application", "prototype", "device",
        "process window", "工程应用", "案例", "工业", "应用", "原型", "工艺窗口",
    ]),
]

_ASCII_KEYWORD = re.compile(r"^[a-z0-9][a-z0-9\s-]*$", re.IGNORECASE)


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _visible_title(material: Mapping[str, Any] | None) -> str:
    if not isinstance(material, Mapping):
        return "这篇文献"
    title = _normalize_text(material.get("title")) or _normalize_text(material.get("title_en"))
    return title or "这篇文献"


def _chunk_text(chunk: Mapping[str, Any]) -> str:
    return _normalize_text(chunk.get("content") or chunk.get("text") or chunk.get("title") or "")


def _build_context_text(
    material: Mapping[str, Any] | None,
    chunks: Sequence[Mapping[str, Any]],
) -> str:
    parts: list[str] = []
    if isinstance(material, Mapping):
        parts.extend([
            material.get("title"),
            material.get("title_en"),
            material.get("summary"),
            material.get("summary_en"),
        ])
        for key in ("focus_points", "focus_points_en"):
            points = material.get(key)
            if isinstance(points, Sequence) and not isinstance(points, (str, bytes)):
                parts.extend(points)
    for chunk in list(chunks)[:MAX_CHUNKS]:
        if isinstance(chunk, Mapping):
            parts.append(_chunk_text(chunk))
    joined = " ".join(_normalize_text(part) for part in parts if _normalize_text(part))
    return joined[:CONTEXT_CHAR_LIMIT]


def _keyword_matches(lower_text: str, keyword: str) -> bool:
    normalized = keyword.lower().strip()
    if not normalized:
        return False
    if _ASCII_KEYWORD.match(normalized):
        pattern = re.compile(
            rf"(^|[^a-z0-9]){re.escape(normalized)}([^a-z0-9]|$)",
            re.IGNORECASE,
        )
        return bool(pattern.search(lower_text))
    return normalized in lower_text


def _keyword_score(text: str, keywords: list[str]) -> int:
    lower = text.lower()
    return sum(1 for keyword in keywords if _keyword_matches(lower, keyword))


def _detect_kind(context_text: str) -> QuestionKind:
    if _keyword_score(context_text, _REVIEW_KEYWORDS) > 0:
        return "review"
    scores = {kind: _keyword_score(context_text, keywords) for kind, keywords in _KEYWORD_RULES}
    for kind, _ in _KEYWORD_RULES:
        if scores.get(kind, 0) > 0:
            return kind
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if ranked and ranked[0][1] > 0:
        return ranked[0][0]
    return "general"


def _review_questions(title: str) -> list[SuggestedQuestion]:
    return [
        {"id": "review-map", "label": "梳理对象", "kind": "review",
         "question": f"{title} 主要梳理了哪些研究对象、材料体系或应用场景？请按类别列出来。"},
        {"id": "review-methods", "label": "技术路线", "kind": "review",
         "question": "这篇综述把哪些实验方法、建模方法或工艺路线放在一起比较？各自适合什么问题？"},
        {"id": "review-consensus", "label": "共识分歧", "kind": "review",
         "question": "文中总结出了哪些稳定共识？哪些结论还存在分歧或证据不足？"},
        {"id": "review-gap", "label": "研究空白", "kind": "review",
         "question": "作者认为下一步最值得做的研究空白是什么？这些空白分别缺少什么证据？"},
    ]


def _welding_questions(title: str) -> list[SuggestedQuestion]:
    return [
        {"id": "welding-material-process", "label": "材料与焊法", "kind": "welding",
         "question": f"{title} 研究了哪些材料或接头形式？使用了哪些焊接方式或关键工艺参数？"},
        {"id": "welding-parameters", "label": "参数影响", "kind": "welding",
         "question": "哪些焊接参数最影响组织、缺陷、强度或疲劳性能？文中给出的证据是什么？"},
        {"id": "welding-microstructure", "label": "组织缺陷", "kind": "welding",
         "question": "热影响区、熔合区或搅拌区发生了什么组织变化？这些变化怎么影响失效？"},
        {"id": "welding-application", "label": "工程边界", "kind": "welding",
         "question": "这项焊接研究适合哪些工程场景？还有哪些材料、厚度、载荷或环境条件没有覆盖？"},
    ]


def _mechanics_questions(title: str) -> list[SuggestedQuestion]:
    return [
        {"id": "mechanics-load", "label": "载荷类型", "kind": "mechanics",
         "question": f"{title} 研究的是静载、疲劳、冲击、循环载荷还是断裂问题？对应的评价指标是什么？"},
        {"id": "mechanics-failure", "label": "失效机制", "kind": "mechanics",
         "question": "主要失效模式是什么？裂纹、塑性变形、界面失效或疲劳损伤从哪里开始？"},
        {"id": "mechanics-method", "label": "测试仿真", "kind": "mechanics",
         "question": "文中用了哪些实验测试或仿真方法？边界条件、样品形状和载荷设置是否合理？"},
        {"id": "mechanics-design", "label": "设计启发", "kind": "mechanics",
         "question": "如果要把结论用于结构设计，哪些参数最应该控制？哪些结论不能直接外推？"},
    ]


def _material_questions(title: str) -> list[SuggestedQuestion]:
    return [
        {"id": "materials-system", "label": "材料体系", "kind": "materials",
         "question": f"{title} 研究了什么材料体系、成分或处理状态？对照组是怎么设置的？"},
        {"id": "materials-method", "label": "表征方法", "kind": "materials",
         "question": "作者用了哪些表征或性能测试方法？每种方法分别证明了什么？"},
        {"id": "materials-mechanism", "label": "性能机制", "kind": "materials",
         "question": "组织、相组成、缺陷或界面变化如何解释性能变化？证据链是否闭合？"},
        {"id": "materials-limit", "label": "适用边界", "kind": "materials",
         "question": "这套材料结论适用于哪些温度、载荷、环境或加工条件？哪些条件还没有验证？"},
    ]


def _method_questions(title: str) -> list[SuggestedQuestion]:
    return [
        {"id": "method-problem", "label": "解决问题", "kind": "method",
         "question": f"{title} 提出的方法主要解决了什么具体问题？输入、输出和评价指标是什么？"},
        {"id": "method-baseline", "label": "对比基线", "kind": "method",
         "question": "它和已有方法、模型或工艺相比改进在哪里？对比实验是否公平？"},
        {"id": "method-data", "label": "数据条件", "kind": "method",
         "question": "方法依赖哪些数据、参数或假设？在小样本、噪声或外部数据下是否可靠？"},
        {"id": "method-transfer", "label": "可迁移性", "kind": "method",
         "question": "如果换一种材料、结构或实验场景，这个方法最可能在哪些环节失效？"},
    ]


def _application_questions(title: str) -> list[SuggestedQuestion]:
    return [
        {"id": "application-scenario", "label": "应用场景", "kind": "application",
         "question": f"{title} 面向什么工程或产业场景？实际约束条件有哪些？"},
        {"id": "application-process", "label": "实施路径", "kind": "application",
         "question": "从实验结果到实际应用，中间还需要哪些工艺、设备、成本或可靠性验证？"},
        {"id": "application-risk", "label": "落地风险", "kind": "application",
         "question": "这项方案的主要失效风险、质量控制难点或规模化边界是什么？"},
        {"id": "application-next", "label": "下一步实验", "kind": "application",
         "question": "如果继续做这个方向，最应该补哪三个验证实验？每个实验要回答什么问题？"},
    ]


def _general_questions(title: str) -> list[SuggestedQuestion]:
    return [
        {"id": "general-object", "label": "研究对象", "kind": "general",
         "question": f"{title} 具体研究了什么对象、问题和场景？请不要泛泛总结，按“对象-方法-结果”列出来。"},
        {"id": "general-method", "label": "方法设计", "kind": "general",
         "question": "作者用了哪些实验、仿真、统计或理论方法？这些方法分别支撑了哪个结论？"},
        {"id": "general-evidence", "label": "证据链", "kind": "general",
         "question": "文中最关键的证据是哪几条？每条证据对应的图表、段落或实验结果是什么？"},
        {"id": "general-limit", "label": "局限边界", "kind": "general",
         "question": "这篇文章哪些结论可以直接借鉴？哪些结论受样本、参数、环境或方法假设限制？"},
    ]


def _questions_for_kind(kind: QuestionKind, title: str) -> list[SuggestedQuestion]:
    if kind == "review":
        return _review_questions(title)
    if kind == "welding":
        return _welding_questions(title)
    if kind == "mechanics":
        return _mechanics_questions(title)
    if kind == "method":
        return _method_questions(title)
    if kind == "application":
        return _application_questions(title)
    if kind == "materials":
        return _material_questions(title)
    return _general_questions(title)


def _dedupe(questions: Sequence[SuggestedQuestion]) -> list[SuggestedQuestion]:
    seen: set[str] = set()
    result: list[SuggestedQuestion] = []
    for question in questions:
        key = str(question.get("question") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(question)
        if len(result) >= QUESTION_LIMIT:
            break
    return result


def build_suggested_questions(
    material: Mapping[str, Any] | None,
    chunks: Sequence[Mapping[str, Any]] | None,
) -> list[SuggestedQuestion]:
    """Return up to ``QUESTION_LIMIT`` deterministic, paper-aware questions.

    Args:
        material: Material metadata mapping (title/summary/focus_points...),
            or ``None`` when the material record is unavailable.
        chunks: The material's chunk dicts (``content``/``text``/``title``),
            or ``None``. Only the leading ``MAX_CHUNKS`` feed the classifier.

    Returns:
        A list of ``{"id", "label", "question", "kind"}`` dicts. The leading
        question of the detected kind embeds the material title; for non-general
        kinds, general questions are appended as a fallback before de-duping.
    """
    safe_chunks = list(chunks) if chunks else []
    title = _visible_title(material)
    context_text = _build_context_text(material, safe_chunks)
    kind = _detect_kind(context_text)
    primary = _questions_for_kind(kind, title)
    fallback = [] if kind == "general" else _general_questions(title)
    return _dedupe([*primary, *fallback])
