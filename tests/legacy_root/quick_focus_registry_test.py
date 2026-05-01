#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
快速验证脚本 - 测试 focus_registry 的基础功能
"""

import sys
from pathlib import Path

# 添加模块路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from layers.focus_registry import FocusRegistry
    print("[OK] focus_registry 模块加载成功")
except ImportError as e:
    print(f"[FAIL] 无法加载 focus_registry: {e}", file=sys.stderr)
    sys.exit(1)

def quick_test():
    """快速测试 FocusRegistry 的基础功能"""

    print("\n" + "=" * 60)
    print("Focus Registry 快速功能测试")
    print("=" * 60)

    # 测试 1: 文本规范化
    print("\n[1] 文本规范化测试")
    test_texts = [
        "热输入",
        "Heat Input",
        "焊接热输入",
        "  热   输   入  "
    ]

    for text in test_texts:
        try:
            normalized = FocusRegistry.normalize_focus_text(text)
            print(f"  [OK] '{text}' -> '{normalized}'")
        except ValueError as e:
            print(f"  [FAIL] '{text}' -> 错误: {e}")

    # 测试 2: 同义词合并
    print("\n[2] 同义词合并测试")
    alias_map = {
        "heat input": "热输入",
        "焊接热输入": "热输入"
    }

    registry = FocusRegistry(alias_map=alias_map)

    test_canonicalize = [
        "热输入",
        "Heat Input",
        "焊接热输入"
    ]

    for text in test_canonicalize:
        canonical = registry.canonicalize_focus(text)
        print(f"  [OK] '{text}' -> canonical='{canonical}'")

    # 测试 3: 关注点去重
    print("\n[3] 关注点去重测试")

    fid1, is_new1 = registry.upsert_focus("热输入", category="工艺参数")
    print(f"  [OK] 插入 '热输入': focus_id={fid1}, is_new={is_new1}")

    fid2, is_new2 = registry.upsert_focus("Heat Input")
    print(f"  [OK] 插入 'Heat Input': focus_id={fid2}, is_new={is_new2}")
    assert fid1 == fid2, f"应该是同一个 ID，但实际是 {fid1} 与 {fid2}"
    print(f"    [OK] 同一个 ID: {fid1 == fid2} (预期: True)")

    # 测试 4: 提及记录
    print("\n[4] 提及记录测试")

    mid1 = registry.add_mention(
        focus_id=fid1,
        doc_id="paper_a",
        doc_title="Test Paper",
        snippet="The heat input affects the HAZ",
        section="results"
    )
    print(f"  [OK] 添加提及: mention_id={mid1}")

    mid2 = registry.add_mention(
        focus_id=fid1,
        doc_id="paper_a",
        doc_title="Test Paper",
        snippet="Increase in heat input",
        section="discussion"
    )
    print(f"  [OK] 添加提及: mention_id={mid2}")

    # 测试 5: 文献映射
    print("\n[5] 文献映射测试")
    registry.update_doc_map("paper_a", "Test Paper", "/path/to/paper_a.pdf")
    print(f"  [OK] 更新 doc_map for paper_a")

    doc_entry = registry.doc_map["paper_a"]
    print(f"    - focus_ids: {doc_entry.focus_ids}")
    print(f"    - focus_names: {doc_entry.focus_names}")
    print(f"    - mention_count: {doc_entry.mention_count}")

    # 验证文献映射的正确性
    assert len(doc_entry.focus_ids) > 0, f"应该有至少 1 个关注点 ID，但实际有 {len(doc_entry.focus_ids)} 个"
    total_mentions = sum(doc_entry.mention_count.values())
    assert total_mentions >= 2, f"应该有至少 2 条提及，但实际有 {total_mentions} 条"
    print(f"    [OK] 文献映射验证通过")

    # 测试 6: 统计和序列化
    print("\n[6] 统计和序列化测试")

    stats = registry.get_statistics()
    print(f"  [OK] 统计信息:")
    for key, value in stats.items():
        print(f"    - {key}: {value}")

    # 序列化字典
    data = registry.to_dict()

    # 验证序列化数据的完整性
    assert 'version' in data, "序列化数据缺少 'version' 字段"
    assert 'points' in data, "序列化数据缺少 'points' 字段"
    assert 'focus_registry' in data, "序列化数据缺少 'focus_registry' 字段"

    print(f"\n  [OK] 序列化为字典:")
    print(f"    - version: {data['version']}")
    print(f"    - points 字段: {data['points']}")
    print(f"    - focus_registry 项数: {len(data['focus_registry'])}")
    print(f"    - doc_map 项数: {len(data['doc_map'])}")
    print(f"    - mentions 项数: {len(data['mentions'])}")

    assert len(data['points']) >= 1, f"应该至少有 1 个关注点，但实际有 {len(data['points'])} 个"
    assert len(data['focus_registry']) >= 1, f"应该至少有 1 条 focus_registry 记录，但实际有 {len(data['focus_registry'])} 条"
    print(f"    [OK] 序列化数据验证通过")

    print("\n" + "=" * 60)
    print("[PASS] 快速测试全部通过!")
    print("=" * 60)

    return True


if __name__ == '__main__':
    try:
        success = quick_test()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[FAIL] 测试失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)