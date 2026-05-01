# -*- coding: utf-8 -*-
"""
inspiration_engine.py
记忆联想引擎：跨论文知识碰撞产生启发点

从 MemPalace 记忆库中检索相关知识碎片，结合 P3 因果推理和 W-Layer 冲突检测，
为用户生成"启发点/创作点"——短小精悍的思路片段，激发写作灵感。
"""

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("InspirationEngine")
_MMR_POOL_SIZE = 20
_MMR_DEFAULT_LAMBDA = 0.7


@dataclass
class InspirationSpark:
    """一条启发点"""
    id: str
    content: str                              # 启发内容（1-3 句话）
    spark_type: str                           # causal_extension | conflict | analogy | gap | synthesis
    source_papers: list[str] = field(default_factory=list)
    confidence: float = 0.5
    related_point_ids: list[str] = field(default_factory=list)
    causal_context: dict[str, Any] = field(default_factory=dict)
    actionable: bool = True                   # 是否可用于续写

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "spark_type": self.spark_type,
            "source_papers": self.source_papers,
            "confidence": round(self.confidence, 3),
            "related_point_ids": self.related_point_ids,
            "causal_context": self.causal_context,
            "actionable": self.actionable,
        }


@dataclass
class ContinuationContext:
    """续写上下文：为 DraftStudio 提供基于启发点的续写材料"""
    spark: InspirationSpark
    evidence_texts: list[str] = field(default_factory=list)
    causal_chain_summary: str = ""
    suggested_angles: list[str] = field(default_factory=list)
    related_figures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spark": self.spark.to_dict(),
            "evidence_texts": self.evidence_texts,
            "causal_chain_summary": self.causal_chain_summary,
            "suggested_angles": self.suggested_angles,
            "related_figures": self.related_figures,
        }


def _spark_id(content: str) -> str:
    return "spark_" + hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]


def _diversify_by_source(items, key, max_per_source: int = 1):
    """Round-robin reorder ``items`` so each ``key(item)`` value contributes
    at most ``max_per_source`` slots before any source repeats.

    Preserves the original (highest-score-first) order within each source
    bucket. Items with an empty key are kept in their relative order at the
    end. Pure-Python, no numpy dependency.
    """
    if not items:
        return items
    buckets: dict[str, list] = {}
    order: list[str] = []
    tail: list = []
    for it in items:
        try:
            k = key(it)
        except (TypeError, AttributeError):
            k = ""
        if not k:
            tail.append(it)
            continue
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(it)

    out: list = []
    while any(buckets[k] for k in order):
        for k in order:
            if buckets[k]:
                out.append(buckets[k].pop(0))
                # Once a source has contributed max_per_source items in this
                # round, defer its remaining items to the next pass.
                if max_per_source > 1:
                    for _ in range(min(max_per_source - 1, len(buckets[k]))):
                        out.append(buckets[k].pop(0))
    out.extend(tail)
    return out


def _resolve_mmr_lambda() -> float:
    raw = os.getenv("MMR_LAMBDA")
    if raw is None:
        return _MMR_DEFAULT_LAMBDA
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _MMR_DEFAULT_LAMBDA
    if 0.0 <= value <= 1.0:
        return value
    return _MMR_DEFAULT_LAMBDA


def _text_terms(text: str) -> list[str]:
    text_lower = text.lower()
    words = re.findall(r"[a-z0-9]+", text_lower)
    cjk_chars = [c for c in text_lower if "\u4e00" <= c <= "\u9fff"]
    bigrams = [
        cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1)
    ]
    if len(cjk_chars) == 1:
        bigrams.append(cjk_chars[0])
    return words + bigrams


def _build_text_embedding(text: str, vocabulary: list[str]) -> list[float]:
    if not vocabulary:
        return []
    terms = _text_terms(text)
    counts = {term: 0.0 for term in vocabulary}
    for term in terms:
        if term in counts:
            counts[term] += 1.0
    return [counts[term] for term in vocabulary]


def _coerce_embedding(value: Any) -> list[float] | None:
    if not isinstance(value, list) or not value:
        return None
    embedding: list[float] = []
    for item in value:
        try:
            embedding.append(float(item))
        except (TypeError, ValueError):
            return None
    return embedding


def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _mmr_similarity(candidate: dict[str, Any], selected: dict[str, Any]) -> float:
    if candidate.get("paper_id") and candidate.get("paper_id") == selected.get("paper_id"):
        return 1.0
    return _cosine_similarity(candidate.get("embedding"), selected.get("embedding"))


def _mmr_select(
    candidates: list[dict[str, Any]],
    query_emb: list[float],
    k: int = 5,
    lam: float = _MMR_DEFAULT_LAMBDA,
) -> list[dict[str, Any]]:
    if not candidates or k <= 0:
        return []

    remaining = list(candidates)
    selected: list[dict[str, Any]] = []
    while remaining and len(selected) < k:
        if selected and lam < 1.0:
            selected_papers = {
                str(item.get("paper_id") or "") for item in selected if item.get("paper_id")
            }
            remaining_papers = {
                str(item.get("paper_id") or "") for item in remaining if item.get("paper_id")
            }
            if remaining_papers and remaining_papers.issubset(selected_papers):
                break
        best_idx = -1
        best_score: float | None = None
        for idx, candidate in enumerate(remaining):
            query_score = float(candidate.get("score", 0.0))
            if "score" not in candidate:
                embedding = candidate.get("embedding")
                query_score = _cosine_similarity(embedding, query_emb)
            diversity_penalty = 0.0
            if selected:
                diversity_penalty = max(
                    _mmr_similarity(candidate, chosen) for chosen in selected
                )
            mmr_score = lam * query_score - (1.0 - lam) * diversity_penalty
            if best_score is None or mmr_score > best_score:
                best_idx = idx
                best_score = mmr_score
        if best_idx < 0:
            break
        selected.append(remaining.pop(best_idx))
    return selected


class InspirationEngine:
    """记忆联想引擎：跨论文知识碰撞产生启发点"""

    def __init__(self, mempalace=None, causal_dags: list[dict] | None = None,
                 conflict_detector=None):
        """
        Args:
            mempalace: MempalaceAdapter 实例（可选；无则只使用本地 DAG）
            causal_dags: 已加载的因果 DAG 列表（来自 04_causal_dag.json）
            conflict_detector: W-Layer ConflictDetector 实例（可选）
        """
        self.mempalace = mempalace
        self.causal_dags = causal_dags or []
        self.conflict_detector = conflict_detector
        self._spark_cache: dict[str, InspirationSpark] = {}

    def generate_sparks(self, query: str, limit: int = 10) -> list[InspirationSpark]:
        """基于用户查询，从记忆中产生联想启发。

        生成策略（叠加）：
        1. memory_association: MemPalace 语义搜索匹配
        2. causal_extension: 因果链延伸推演
        3. conflict: 矛盾碰撞产生的探索点
        4. gap: 覆盖度分析找空白
        5. synthesis: 多源融合总结
        """
        sparks: list[InspirationSpark] = []

        # 策略1: 记忆联想
        sparks.extend(self._memory_association_sparks(query, limit=limit))

        # 策略2: 因果链延伸
        sparks.extend(self._causal_extension_sparks(query, limit=limit))

        # 策略3: 冲突碰撞
        sparks.extend(self._conflict_sparks(query))

        # 策略4: 覆盖度缺口
        sparks.extend(self._gap_sparks(query))

        # 去重 + 排序
        seen_ids = set()
        unique = []
        for s in sparks:
            if s.id not in seen_ids:
                seen_ids.add(s.id)
                unique.append(s)
        unique.sort(key=lambda s: s.confidence, reverse=True)
        result = unique[:limit]

        # 缓存以便后续续写
        for s in result:
            self._spark_cache[s.id] = s

        return result

    def generate_sparks_from_chunks(self, query: str, chunks: list[dict], limit: int = 10) -> list[InspirationSpark]:
        """从原始文本切片生成启发点（当无 DAG/MemPalace 数据时的降级路径）。"""
        if not chunks:
            return []

        query_lower = query.lower()
        # ASCII 空格分词（保留对英文 query 的原有行为）
        query_words = [w for w in query_lower.split() if len(w) > 1]
        # CJK 字符 bigram（修复中文 query 因无空格而完全失配的退化问题）
        cjk_chars = [c for c in query_lower if "\u4e00" <= c <= "\u9fff"]
        query_bigrams = [
            cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1)
        ]
        total_terms = len(query_words) + len(query_bigrams)

        scored: list[tuple[float, dict]] = []
        for chunk in chunks:
            content = str(chunk.get("content") or "").strip()
            if len(content) < 20:
                continue
            if total_terms > 0:
                content_lower = content.lower()
                hits = sum(1 for w in query_words if w in content_lower)
                hits += sum(1 for bg in query_bigrams if bg in content_lower)
                score = hits / total_terms
            else:
                score = 0.3
            scored.append((score, chunk))

        if not scored:
            return []

        scored.sort(key=lambda x: x[0], reverse=True)
        pool = scored[:max(limit, _MMR_POOL_SIZE)]
        vocabulary = list(dict.fromkeys(
            _text_terms(query) + [
                term
                for _, chunk in pool
                for term in _text_terms(str(chunk.get("content") or ""))
            ]
        ))
        query_emb = _build_text_embedding(query, vocabulary)
        candidates = []
        for score, chunk in pool:
            embedding = _coerce_embedding(chunk.get("embedding"))
            if embedding is None:
                embedding = _build_text_embedding(str(chunk.get("content") or ""), vocabulary)
            candidates.append(
                {
                    "score": score,
                    "paper_id": str(
                        chunk.get("material_id")
                        or chunk.get("paper_id")
                        or chunk.get("title")
                        or ""
                    ),
                    "embedding": embedding,
                    "chunk": chunk,
                }
            )
        selected = _mmr_select(
            candidates,
            query_emb,
            k=limit,
            lam=_resolve_mmr_lambda(),
        )

        sparks: list[InspirationSpark] = []
        for candidate in selected:
            score = float(candidate.get("score", 0.0))
            chunk = candidate["chunk"]
            content = str(chunk.get("content") or "")[:350]
            title = str(chunk.get("title") or "未知来源")
            chunk_idx = int(chunk.get("chunk_index") or 0)
            spark_content = f"《{title}》片段{chunk_idx + 1}：{content}"
            spark = InspirationSpark(
                id=_spark_id(spark_content),
                content=spark_content[:400],
                spark_type="memory_association",
                source_papers=[title],
                confidence=min(0.45 + score * 0.4, 0.92),
                actionable=True,
            )
            self._spark_cache[spark.id] = spark
            sparks.append(spark)

        return sparks

    def get_continuation_context(self, spark_id: str) -> Optional[ContinuationContext]:
        """为 DraftStudio 续写提供上下文。

        返回启发点原文 + 来源证据 + 因果上下文 + 建议角度。
        """
        spark = self._spark_cache.get(spark_id)
        if not spark:
            return None

        evidence_texts = []
        # 从 MemPalace 检索相关证据
        if self.mempalace and hasattr(self.mempalace, "search"):
            try:
                result = self.mempalace.search(spark.content, limit=5)
                if hasattr(result, "results"):
                    for hit in result.results:
                        doc = hit.document if hasattr(hit, "document") else str(hit)
                        if doc and len(doc) > 10:
                            evidence_texts.append(doc)
            except Exception as e:
                logger.debug("检索续写证据失败: %s", e)

        # 因果链摘要
        causal_summary = ""
        if spark.causal_context:
            nodes = spark.causal_context.get("chain_nodes", [])
            rels = spark.causal_context.get("chain_relations", [])
            if nodes and rels:
                parts = []
                for i, node in enumerate(nodes):
                    parts.append(node)
                    if i < len(rels):
                        parts.append(f" --[{rels[i]}]--> ")
                causal_summary = "".join(parts)

        # 建议续写角度
        angles = self._suggest_angles(spark)

        return ContinuationContext(
            spark=spark,
            evidence_texts=evidence_texts,
            causal_chain_summary=causal_summary,
            suggested_angles=angles,
        )

    # ------ 私有策略方法 ------

    def _memory_association_sparks(self, query: str, limit: int = 5) -> list[InspirationSpark]:
        """从 MemPalace 语义搜索中提取联想启发"""
        if not self.mempalace or not hasattr(self.mempalace, "search"):
            return []

        try:
            if not self.mempalace.is_enabled():
                return []
            result = self.mempalace.search(query, wing="literature", limit=limit)
            if not hasattr(result, "results") or not result.available:
                return []
        except Exception as e:
            logger.debug("MemPalace 搜索失败: %s", e)
            return []

        sparks = []
        for hit in result.results:
            doc = hit.document if hasattr(hit, "document") else str(hit)
            if not doc or len(doc) < 10:
                continue

            meta = hit.metadata if hasattr(hit, "metadata") else {}
            paper_title = meta.get("paper_title", "未知来源") if isinstance(meta, dict) else "未知来源"

            spark = InspirationSpark(
                id=_spark_id(doc),
                content=doc.strip()[:300],
                spark_type="memory_association",
                source_papers=[paper_title],
                confidence=0.7,
                related_point_ids=[meta.get("writing_point_id", "")] if isinstance(meta, dict) else [],
                actionable=True,
            )
            sparks.append(spark)

        return sparks

    def _causal_extension_sparks(self, query: str, limit: int = 5) -> list[InspirationSpark]:
        """从因果 DAG 中寻找可延伸的推理链，产生启发"""
        sparks = []
        query_terms = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', query.lower()))
        if not query_terms:
            return []

        for dag in self.causal_dags:
            links = dag.get("links", [])
            nodes_set = {n["id"] for n in dag.get("nodes", [])}

            # 找到与 query 相关的节点
            relevant_nodes = set()
            for node_id in nodes_set:
                node_terms = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', node_id.lower()))
                if query_terms & node_terms:
                    relevant_nodes.add(node_id)

            if not relevant_nodes:
                continue

            # 沿因果链向下游/上游延伸
            for link in links:
                src, tgt = link.get("source", ""), link.get("target", "")
                rel = link.get("relation", "→")
                conf = link.get("confidence", 0.5)

                if src in relevant_nodes and tgt not in relevant_nodes:
                    # 向下游延伸：query相关 → 新发现
                    content = f"「{src}」{rel}「{tgt}」— 这条因果链值得进一步探索"
                    spark = InspirationSpark(
                        id=_spark_id(content),
                        content=content,
                        spark_type="causal_extension",
                        confidence=conf * 0.9,
                        causal_context={"chain_nodes": [src, tgt], "chain_relations": [rel]},
                        actionable=True,
                    )
                    sparks.append(spark)
                elif tgt in relevant_nodes and src not in relevant_nodes:
                    # 向上游回溯：什么导致了 query 关注的现象
                    content = f"「{src}」可能是「{tgt}」的上游因素（关系: {rel}）"
                    spark = InspirationSpark(
                        id=_spark_id(content),
                        content=content,
                        spark_type="causal_extension",
                        confidence=conf * 0.85,
                        causal_context={"chain_nodes": [src, tgt], "chain_relations": [rel]},
                        actionable=True,
                    )
                    sparks.append(spark)

        sparks.sort(key=lambda s: s.confidence, reverse=True)
        return sparks[:limit]

    def _conflict_sparks(self, query: str) -> list[InspirationSpark]:
        """从 W-Layer 冲突检测结果中产生碰撞启发"""
        if not self.conflict_detector:
            return []

        try:
            conflicts = self.conflict_detector.detect_conflicts()
        except Exception as e:
            logger.debug("冲突检测失败: %s", e)
            return []

        sparks = []
        for param_info in conflicts.get("high_conflict_parameters", []):
            param = param_info.get("parameter", "")
            papers = param_info.get("papers", [])
            claims_list = param_info.get("claims", [])

            if len(claims_list) < 2:
                continue

            claim_texts = [c.get("text", "") for c in claims_list[:3]]
            content = (
                f"关于「{param}」，不同论文得出了矛盾结论：\n"
                + "\n".join(f"  · {t[:100]}" for t in claim_texts if t)
                + f"\n可能与实验条件差异有关，值得深入分析"
            )
            spark = InspirationSpark(
                id=_spark_id(f"conflict_{param}"),
                content=content,
                spark_type="conflict",
                source_papers=list(set(papers))[:5],
                confidence=0.85,
                actionable=True,
            )
            sparks.append(spark)

        return sparks

    def _gap_sparks(self, query: str) -> list[InspirationSpark]:
        """分析覆盖度缺口，找出文献未涉及的角度"""
        if not self.causal_dags:
            return []

        # 收集所有 DAG 中出现的实体
        all_entities = set()
        entity_paper_count: dict[str, int] = {}
        for dag in self.causal_dags:
            dag_entities = {n["id"] for n in dag.get("nodes", [])}
            all_entities.update(dag_entities)
            for ent in dag_entities:
                entity_paper_count[ent] = entity_paper_count.get(ent, 0) + 1

        # 找只被1篇论文覆盖的实体 → 潜在补充点
        sparks = []
        for entity, count in entity_paper_count.items():
            if count == 1 and len(entity) > 3:
                content = f"「{entity}」目前仅有1篇论文涉及，可能是一个值得补充研究的方向"
                sparks.append(InspirationSpark(
                    id=_spark_id(f"gap_{entity}"),
                    content=content,
                    spark_type="gap",
                    confidence=0.5,
                    actionable=False,
                ))

        sparks.sort(key=lambda s: len(s.content), reverse=True)
        return sparks[:3]

    def _suggest_angles(self, spark: InspirationSpark) -> list[str]:
        """为给定启发点建议续写角度"""
        angles = []
        if spark.spark_type == "causal_extension":
            angles.append("沿因果链进一步论证，补充实验证据")
            angles.append("讨论这一因果关系的边界条件")
        elif spark.spark_type == "conflict":
            angles.append("分析矛盾结论的实验条件差异")
            angles.append("提出可能的统一解释框架")
        elif spark.spark_type == "memory_association":
            angles.append("引用此发现支撑当前论点")
            angles.append("对比当前研究与该发现的异同")
        elif spark.spark_type == "gap":
            angles.append("设计新实验填补这一空白")
            angles.append("文献综述中标注此方向的研究不足")
        elif spark.spark_type == "synthesis":
            angles.append("综合多源证据得出新见解")
            angles.append("构建系统性的参数-性能映射")
        return angles


def load_causal_dags_from_output(output_root: str | Path) -> list[dict]:
    """从批处理输出目录加载所有论文的因果 DAG"""
    output_root = Path(output_root)
    dags = []
    for dag_file in output_root.rglob("04_causal_dag.json"):
        try:
            with open(dag_file, "r", encoding="utf-8") as f:
                dag = json.load(f)
            if isinstance(dag, dict) and dag.get("nodes"):
                dag["_source_dir"] = str(dag_file.parent.name)
                dags.append(dag)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("加载因果 DAG 失败: %s - %s", dag_file, e)
    logger.info("从 %s 加载了 %d 个因果 DAG", output_root, len(dags))
    return dags
