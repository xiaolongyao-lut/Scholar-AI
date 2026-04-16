from __future__ import annotations

from routers.resources_router import structure_aware_chunk


def test_structure_chunk_preserves_table_and_section_title() -> None:
    text = "# 方法\nA|B\n1|2\n\n段落说明内容。"
    out = structure_aware_chunk(text=text, material_id="m1", title="doc1")

    assert out
    assert any(chunk.chunk_type == "table" for chunk in out)
    assert all(bool(chunk.section_title) for chunk in out)
    assert all(chunk.material_id == "m1" for chunk in out)
    assert all(chunk.title == "doc1" for chunk in out)
