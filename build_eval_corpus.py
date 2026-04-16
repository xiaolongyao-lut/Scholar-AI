"""build_eval_corpus.py — 从已有 chunk_store 构建评测语料与对齐的 eval queries.

用法:
    python build_eval_corpus.py

功能:
1. 读取 output/chunk_store/ 下所有真实 chunk 数据
2. 从每篇文献中自动提取内容关键词，生成与其内容对齐的评测查询
3. 将 eval_queries_v1.0.jsonl 中的 doc_id 映射到真实 material_id
4. 输出 eval_queries_v2.0.jsonl — 可直接被 eval_retrieval_runtime.py 使用
"""

from __future__ import annotations

import json
from pathlib import Path


def load_all_chunks(chunk_store_dir: Path) -> dict[str, list[dict]]:
    """加载所有 chunk，返回 {material_id: [chunk, ...]}"""
    materials: dict[str, list[dict]] = {}
    for fp in chunk_store_dir.glob("*.json"):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            raw = payload.get("chunks")
            if isinstance(raw, list):
                # {"chunks": [...]}
                for c in raw:
                    if isinstance(c, dict):
                        mid = c.get("material_id", "unknown")
                        materials.setdefault(mid, []).append(c)
            else:
                # {material_id: [chunk, ...]}
                for mid, cs in payload.items():
                    if isinstance(cs, list):
                        for c in cs:
                            if isinstance(c, dict):
                                materials.setdefault(mid, []).append(c)
    return materials


def extract_keywords(chunks: list[dict]) -> list[str]:
    """从 chunk 内容中提取领域关键词"""
    text = " ".join(c.get("content", "") or c.get("text", "") for c in chunks[:10]).lower()
    kw_map = {
        "激光焊接": ["laser", "激光"],
        "熔池": ["熔池", "molten pool", "melt pool", "weld pool", "keyhole"],
        "微观组织": ["microstructure", "微观", "组织", "grain", "晶粒"],
        "力学性能": ["hardness", "硬度", "tensile", "拉伸", "strength", "强度", "fatigue", "疲劳"],
        "裂纹/缺陷": ["crack", "裂纹", "defect", "缺陷", "porosity", "气孔"],
        "钛合金": ["titanium", "ti-6al", "钛合金", "ti–6al"],
        "铝合金": ["aluminum", "aluminium", "铝合金", "al-"],
        "热处理": ["heat treatment", "热处理", "nitriding", "渗氮", "diffusion"],
        "耐磨性": ["wear", "磨损", "耐磨", "tribolog"],
        "数值模拟": ["simulation", "模拟", "finite element", "有限元", "numerical"],
        "深度学习": ["deep learning", "neural network", "深度学习", "机器学习"],
        "电弧焊": ["arc weld", "电弧", "tig", "mig", "gmaw"],
        "腐蚀": ["corrosion", "腐蚀"],
        "残余应力": ["residual stress", "残余应力"],
        "X射线": ["x-ray", "x射线", "synchrotron"],
        "传热": ["heat transfer", "传热", "thermal"],
    }

    found = []
    for topic, patterns in kw_map.items():
        if any(p in text for p in patterns):
            found.append(topic)
    return found


QUERY_TEMPLATES = {
    "simple": [
        "{topic}的最新研究进展",
        "{topic}的基本原理和方法",
        "关于{topic}的文献综述",
    ],
    "medium": [
        "{topic1}与{topic2}之间的关系研究",
        "{topic1}对{topic2}的影响机制",
        "如何通过实验验证{topic1}的{topic2}",
    ],
    "hard": [
        "{topic1}在{topic2}条件下对{topic3}的耦合效应分析",
        "多学科交叉视角下{topic1}与{topic2}的{topic3}研究",
    ],
}


def generate_queries_for_material(
    material_id: str,
    title: str,
    keywords: list[str],
    start_id: int,
) -> list[dict]:
    """为单篇文献生成若干评测 query"""
    queries: list[dict] = []
    qid = start_id

    # Simple queries
    for tmpl in QUERY_TEMPLATES["simple"]:
        for kw in keywords[:3]:
            qid += 1
            queries.append({
                "query_id": f"q_{qid:04d}",
                "query_text": tmpl.format(topic=kw),
                "target_section": "auto",
                "relevance_tags": ["corpus_aligned"],
                "difficulty_level": "simple",
                "evidence_set": [
                    {"doc_id": material_id, "section": "content", "mention_count": 1}
                ],
                "expected_recall_at_k": {"recall_at_1": 0.8, "recall_at_3": 0.9},
                "source": "build_eval_corpus",
                "source_title": title,
            })

    # Medium queries
    if len(keywords) >= 2:
        for tmpl in QUERY_TEMPLATES["medium"]:
            for i in range(min(3, len(keywords) - 1)):
                qid += 1
                queries.append({
                    "query_id": f"q_{qid:04d}",
                    "query_text": tmpl.format(topic1=keywords[i], topic2=keywords[i + 1]),
                    "target_section": "auto",
                    "relevance_tags": ["corpus_aligned"],
                    "difficulty_level": "medium",
                    "evidence_set": [
                        {"doc_id": material_id, "section": "content", "mention_count": 1}
                    ],
                    "expected_recall_at_k": {"recall_at_1": 0.6, "recall_at_3": 0.8},
                    "source": "build_eval_corpus",
                    "source_title": title,
                })

    # Hard queries
    if len(keywords) >= 3:
        for tmpl in QUERY_TEMPLATES["hard"]:
            qid += 1
            queries.append({
                "query_id": f"q_{qid:04d}",
                "query_text": tmpl.format(
                    topic1=keywords[0], topic2=keywords[1], topic3=keywords[2]
                ),
                "target_section": "auto",
                "relevance_tags": ["corpus_aligned"],
                "difficulty_level": "hard",
                "evidence_set": [
                    {"doc_id": material_id, "section": "content", "mention_count": 1}
                ],
                "expected_recall_at_k": {"recall_at_1": 0.4, "recall_at_3": 0.6},
                "source": "build_eval_corpus",
                "source_title": title,
            })

    return queries


def also_add_man2011_to_chunk_store(chunk_store_dir: Path) -> str | None:
    """将 Man 等 2011 论文的 full_extract 加入 chunk_store，返回 material_id"""
    extract_path = (
        Path("output")
        / "Man 等 - 2011 - Laser diffusion nitriding of Ti–6Al–4V for improving hardness and wear resistance"
        / "01_full_extract.json"
    )
    if not extract_path.exists():
        return None

    data = json.loads(extract_path.read_text(encoding="utf-8"))
    raw_chunks = data.get("chunks", [])
    if not raw_chunks:
        return None

    material_id = "mat_man2011_ti6al4v"
    title = "Man 等 - 2011 - Laser diffusion nitriding of Ti–6Al–4V"

    # 转换为 chunk_store 标准格式
    chunks = []
    for i, c in enumerate(raw_chunks):
        text = c.get("text", "").strip()
        if not text or len(text) < 10:
            continue
        chunks.append({
            "chunk_id": f"{material_id}_chunk_{i}",
            "material_id": material_id,
            "title": title,
            "section_title": c.get("section_title", ""),
            "chunk_index": i,
            "content": text,
            "char_count": len(text),
            "page": c.get("page", 0),
        })

    if not chunks:
        return None

    out_path = chunk_store_dir / "man2011_chunks.json"
    out_path.write_text(
        json.dumps({material_id: chunks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[+] Man2011: {len(chunks)} chunks → {out_path}")
    return material_id


def main():
    chunk_store_dir = Path("output") / "chunk_store"
    if not chunk_store_dir.exists():
        print("ERROR: output/chunk_store/ 不存在")
        return

    # Step 1: 加入 Man 2011
    also_add_man2011_to_chunk_store(chunk_store_dir)

    # Step 2: 加载所有 chunks
    materials = load_all_chunks(chunk_store_dir)
    print(f"\n共加载 {len(materials)} 篇文献, {sum(len(v) for v in materials.values())} 个 chunks")

    # Step 3: 为每篇文献生成 query
    all_queries: list[dict] = []
    qid_counter = 0

    for mid, chunks in materials.items():
        if not chunks:
            continue
        title = chunks[0].get("title", mid)
        keywords = extract_keywords(chunks)
        if not keywords:
            print(f"  SKIP {mid}: no keywords found")
            continue

        queries = generate_queries_for_material(mid, title, keywords, qid_counter)
        qid_counter += len(queries)
        all_queries.extend(queries)
        print(f"  {mid[:20]}... | {title[:40]} | kw={keywords[:5]} | +{len(queries)}q")

    # Step 4: 写出 eval_queries_v2.0.jsonl
    out_path = Path("eval_queries_v2.0.jsonl")
    with out_path.open("w", encoding="utf-8") as f:
        for q in all_queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    print(f"\n✅ 生成 {len(all_queries)} 条评测查询 → {out_path}")
    print(f"   涉及 {len(set(q['evidence_set'][0]['doc_id'] for q in all_queries))} 篇文献")

    # 统计难度分布
    diff_counts = {}
    for q in all_queries:
        d = q["difficulty_level"]
        diff_counts[d] = diff_counts.get(d, 0) + 1
    print(f"   难度分布: {diff_counts}")


if __name__ == "__main__":
    main()
