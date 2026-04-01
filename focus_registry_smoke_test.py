# -*- coding: utf-8 -*-
"""
Focus Registry Smoke Test

验证关注点规范化、去重、文献映射的三个核心用例：

用例 1: 同一篇文献里出现同义词，最终 focus_registry 里只能有 1 个 canonical focus
用例 2: 同一篇文献同时提到多个不同关注点，doc_map 里能正确记录所有不同的关注点
用例 3: semantic_router.py 可以读取新版 focus_points.json，且仍能拿到标准关注点列表
"""

import json
import sys
import tempfile
import traceback
from pathlib import Path

# 添加模块路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from layers.focus_registry import FocusRegistry
from layers.semantic_router import SemanticRouter

# ============================================================================
# 用例 1: 同义词自动归并
# ============================================================================

def test_case_1_synonym_consolidation():
    """
    输入: 同一篇文献中出现 "热输入", "焊接热输入", "heat input" 三个表述
    期望: focus_registry 中只有 1 个 canonical focus，但 mentions 中有 3 条记录
    """
    print("\n" + "=" * 60)
    print("用例 1: 同义词自动归并")
    print("=" * 60)

    # 创建别名表
    alias_map = {
        "焊接热输入": "热输入",
        "heat input": "热输入"
    }

    # 初始化 registry
    registry = FocusRegistry(alias_map=alias_map)

    # 模拟从文献中提取的三个原始短语
    raw_focuses = [
        ("heat input", "With increase in the heat input, the HAZ width increases"),
        ("焊接热输入", "The 焊接热输入 directly affects cooling rate"),
        ("热输入", "Increase 热输入 reduces cooling")
    ]

    # 插入这些关注点
    focus_ids = []
    for text, snippet in raw_focuses:
        focus_id, is_new = registry.upsert_focus(
            text,
            canonical_name="热输入",
            category="工艺参数"
        )
        focus_ids.append(focus_id)

        # 添加提及
        registry.add_mention(
            focus_id=focus_id,
            doc_id="paper_a",
            doc_title="Test Paper A",
            snippet=snippet,
            section="results"
        )

    # 验证
    print("\n[OK] 检查 focus_registry")
    print(f"  - focus_registry 中的条目数: {len(registry.focus_records)}")
    if len(registry.focus_records) != 1:
        raise AssertionError(f"应该只有 1 个 canonical focus，但实际有 {len(registry.focus_records)} 个")
    print(f"    [OK] 只有 1 个 canonical focus (预期: 1)")

    focus_record = next(iter(registry.focus_records.values()))
    print(f"  - canonical_name: {focus_record.canonical_name}")
    print(f"  - aliases: {focus_record.aliases}")
    print(f"  - mention_count: {focus_record.mention_count}")
    if focus_record.mention_count != 3:
        raise AssertionError(f"应该有 3 条 mention，但实际有 {focus_record.mention_count} 条")
    print(f"    [OK] 有 3 条 mention (预期: 3)")

    print("\n[OK] 检查 mentions")
    mentions = registry.get_mentions_for_focus(focus_record.id)
    print(f"  - 总条数: {len(mentions)}")
    for i, mention in enumerate(mentions, 1):
        print(f"    {i}. doc_id={mention.doc_id}, snippet='{mention.snippet[:30]}...'")
    if len(mentions) != 3:
        raise AssertionError(f"应该有 3 条 mention，但实际有 {len(mentions)} 条")
    print(f"    [OK] 所有 3 条 mention 都正确记录 (预期: 3)")

    print("\n[OK] 用例 1 通过")
    return True


# ============================================================================
# 用例 2: 多关注点文献映射
# ============================================================================

def test_case_2_multi_focus_doc_mapping():
    """
    输入: paper_a 提到 "热输入" 和 "晶粒细化"，paper_b 只提到 "热输入"，paper_c 提到 "晶粒细化" 和 "参数优化"
    期望: doc_map 中每篇文献都准确映射到其涉及的关注点集合，无重复、无遗漏
    """
    print("\n" + "=" * 60)
    print("用例 2: 多关注点文献映射")
    print("=" * 60)

    # 初始化 registry
    registry = FocusRegistry()

    # 插入关注点
    focus_ids = {}
    for focus_text, category in [
        ("热输入", "工艺参数"),
        ("晶粒细化", "组织控制"),
        ("参数优化", "工艺参数")
    ]:
        fid, _ = registry.upsert_focus(focus_text, category=category)
        focus_ids[focus_text] = fid

    # 模拟三篇文献的提及关系
    documents = {
        "paper_a": {
            "title": "Laser Welding Parameters",
            "focuses": [
                ("热输入", "The heat input was set to 2 kW"),
                ("晶粒细化", "Grain refinement was observed")
            ]
        },
        "paper_b": {
            "title": "Thermal Control in Welding",
            "focuses": [
                ("热输入", "Input heat affects cooling rate")
            ]
        },
        "paper_c": {
            "title": "Parameter Optimization Study",
            "focuses": [
                ("晶粒细化", "Fine grain structure achieved"),
                ("参数优化", "Parameters were optimized")
            ]
        }
    }

    # 添加 mentions 并更新 doc_map
    for doc_id, doc_info in documents.items():
        for focus_text, snippet in doc_info["focuses"]:
            fid = focus_ids[focus_text]
            registry.add_mention(
                focus_id=fid,
                doc_id=doc_id,
                doc_title=doc_info["title"],
                snippet=snippet,
                section="text"
            )

        registry.update_doc_map(doc_id, doc_info["title"])

    # 验证
    print("\n[OK] 检查 doc_map")

    expected_mapping = {
        "paper_a": ["热输入", "晶粒细化"],
        "paper_b": ["热输入"],
        "paper_c": ["晶粒细化", "参数优化"]
    }

    for doc_id, expected_focuses in expected_mapping.items():
        doc_entry = registry.doc_map[doc_id]
        actual_focuses = doc_entry.focus_names

        print(f"\n  {doc_id}:")
        print(f"    期望: {sorted(expected_focuses)}")
        print(f"    实际: {sorted(actual_focuses)}")
        print(f"    mention_count: {doc_entry.mention_count}")

        if set(actual_focuses) != set(expected_focuses):
            raise AssertionError(
                f"{doc_id} 的关注点映射不正确。期望: {set(expected_focuses)}, 实际: {set(actual_focuses)}"
            )
        print(f"    [OK] 映射正确")

    print("\n[OK] 用例 2 通过")
    return True


# ============================================================================
# 用例 3: semantic_router 兼容性
# ============================================================================

def test_case_3_semantic_router_compatibility():
    """
    输入: 新版 focus_points.json（包含 focus_registry、doc_map、mentions）
    期望: semantic_router 能正确读取，并从中提取标准关注点列表进行向量化
    """
    print("\n" + "=" * 60)
    print("用例 3: semantic_router 兼容性")
    print("=" * 60)

    # 创建一个临时的 focus_points.json
    with tempfile.TemporaryDirectory() as tmpdir:
        focus_json_path = Path(tmpdir) / "focus_points.json"

        # 生成新版 schema 的 JSON
        # 使用 safe_root 参数允许在临时目录中保存文件
        registry = FocusRegistry(safe_root=tmpdir)

        # 插入几个关注点
        for text, category in [
            ("热输入", "工艺参数"),
            ("晶粒细化", "组织控制"),
            ("冷却速率", "工艺参数")
        ]:
            registry.upsert_focus(text, category=category)

        # 保存到文件
        registry.save(str(focus_json_path))
        print(f"\n[OK] 已生成新版 focus_points.json: {focus_json_path}")

        # 验证 JSON 结构
        with open(focus_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        print("\n[OK] 检查 JSON schema")
        required_keys = ["version", "points", "focus_registry", "doc_map", "mentions", "metadata"]
        for key in required_keys:
            if key not in data:
                raise AssertionError(f"缺少必要字段 '{key}'。可用字段: {list(data.keys())}")
            print(f"  [OK] {key}: 存在")

        print(f"\n[OK] 检查 points 字段（向后兼容）")
        print(f"  - 长度: {len(data['points'])}")
        print(f"  - 内容: {data['points']}")
        if len(data['points']) != 3:
            raise AssertionError(f"points 应该有 3 个元素，但实际有 {len(data['points'])} 个: {data['points']}")
        print(f"    [OK] points 字段包含 3 个标准关注点")

        print(f"\n[OK] 检查 focus_registry 字段（必须是列表）")
        print(f"  - 类型: {type(data['focus_registry'])}")
        print(f"  - 长度: {len(data['focus_registry'])}")
        if not isinstance(data['focus_registry'], list):
            raise AssertionError(f"focus_registry 必须是列表，但实际是 {type(data['focus_registry'])}")
        print(f"    [OK] focus_registry 是列表")

        for record in data['focus_registry']:
            print(f"    - {record['canonical_name']} (id={record['id']}, category={record['category']})")
        if len(data['focus_registry']) != 3:
            raise AssertionError(f"focus_registry 应该有 3 个元素，但实际有 {len(data['focus_registry'])} 个")
        print(f"    [OK] focus_registry 包含 3 个规范化的关注点")

        # [PASS] 实际测试 semantic_router 的 _load_focus_points 方法
        print(f"\n[OK] 实际测试 semantic_router._load_focus_points 方法")
        try:
            # 创建路由器实例，使用虚拟 API key（仅测试加载，不调用 API）
            # WARNING: 下面的 API key 是测试用关键字。不要将其用于实际生产代码中。
            router = SemanticRouter(
                api_key="test_api_key_for_smoke_test",
                focus_points_path=str(focus_json_path),
                lazy_vectorize=True  # 延迟向量化，避免实际 API 调用
            )

            # 验证加载结果
            print(f"  - 加载的关注点数: {len(router.focus_points)}")
            print(f"  - 关注点内容: {router.focus_points}")

            expected_points = {"热输入", "晶粒细化", "冷却速率"}
            actual_points = set(router.focus_points)

            if actual_points != expected_points:
                raise AssertionError(
                    f"加载的关注点不匹配。期望: {expected_points}, 实际: {actual_points}"
                )
            print(f"    [OK] semantic_router 正确加载了关注点")

            if len(router.focus_points) != 3:
                raise AssertionError(
                    f"应该加载 3 个关注点，但实际加载 {len(router.focus_points)} 个"
                )
            print(f"    [OK] 关注点数量正确 (count={len(router.focus_points)})")

        except Exception as e:
            print(f"  [FAIL] semantic_router 加载失败: {e}")
            traceback.print_exc()
            raise

    print("\n[OK] 用例 3 通过")
    return True


# ============================================================================
# 汇总和报告
# ============================================================================

def run_all_tests():
    """运行所有 smoke test"""
    print("\n" + "#" * 60)
    print("# Focus Registry Smoke Test Suite")
    print("#" * 60)

    tests = [
        ("用例 1", test_case_1_synonym_consolidation),
        ("用例 2", test_case_2_multi_focus_doc_mapping),
        ("用例 3", test_case_3_semantic_router_compatibility)
    ]

    results = {}
    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = ("[PASS]", result)
        except Exception as e:
            print(f"\n[FAIL] {test_name} 失败: {e}")
            results[test_name] = ("[FAIL]", str(e))

    # 生成报告
    print("\n" + "#" * 60)
    print("# 测试报告总结")
    print("#" * 60)

    passed = sum(1 for status, _ in results.values() if "PASS" in status)
    total = len(results)

    for test_name, (status, _) in results.items():
        print(f"{status} {test_name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n[PASS] 所有 smoke test 都通过了!")
        return True
    else:
        print(f"\n[FAIL] 有 {total - passed} 个测试失败")
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
