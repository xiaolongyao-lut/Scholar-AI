# -*- coding: utf-8 -*-
"""
GraphRAG Synthesis Bridge (v2.0 Production)
Role: Global Context & Community Reports Integration

职责边界：
    1. 读取 Microsoft GraphRAG 索引产物 (communities / community_reports / entities parquet)
    2. 按社区层级 (level) 过滤并返回标准化社区数据
    3. 按实体名/别名做大小写无关匹配，联合关联 communities 与 community_reports
    4. 不做下游业务推理、不做 LLM 调用

依赖策略：
    - 有 pandas + pyarrow 时直接读 parquet
    - 有 graphrag 官方 reader 时优先走官方 reader
    - 缺文件时抛 FileNotFoundError，不吞异常
    - 缺 pandas/pyarrow 时在 __init__ 阶段抛 ImportError

对齐 GraphRAG 官方 Schema：
    entities.parquet:          id, name, type, description, text_unit_ids
    communities.parquet:       id, community, level, title, entity_ids, relationship_ids, size
    community_reports.parquet: id, community, level, title, summary, full_content, rank, findings
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Set

# ─── 可选依赖探测 ─────────────────────────────────────────────────
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pd = None  # type: ignore[assignment]
    HAS_PANDAS = False

try:
    import graphrag  # noqa: F401
    HAS_GRAPHRAG = True
except ImportError:
    HAS_GRAPHRAG = False

# ─── 模块级日志 ───────────────────────────────────────────────────
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logger.addHandler(logging.NullHandler())


class GraphRAGBridge:
    """
    GraphRAG 全局社区检索桥：读取 GraphRAG 索引三表并提供社区过滤与实体关联查询。

    使用示例::

        bridge = GraphRAGBridge(index_path="./output/artifacts")
        communities = bridge.get_global_communities(level=1)
        associations = bridge.get_entity_association("laser power")
    """

    # 文件名常量 (对齐 GraphRAG 官方输出路径)
    FILE_COMMUNITIES: str = "communities.parquet"
    FILE_COMMUNITY_REPORTS: str = "community_reports.parquet"
    FILE_ENTITIES: str = "entities.parquet"

    # 必须存在的三张表
    REQUIRED_FILES: tuple = (FILE_COMMUNITIES, FILE_COMMUNITY_REPORTS, FILE_ENTITIES)

    def __init__(self, index_path: str = "./index") -> None:
        """
        初始化 GraphRAG Bridge。

        Args:
            index_path: GraphRAG 索引产物根目录，至少包含三张 parquet。

        Raises:
            ImportError: 缺少 pandas / pyarrow 时。
            FileNotFoundError: 索引目录不存在或缺少必要 parquet 文件时。
        """
        if not HAS_PANDAS:
            raise ImportError(
                "GraphRAGBridge requires pandas and pyarrow. "
                "Install via: pip install pandas pyarrow"
            )

        if not os.path.isdir(index_path):
            raise FileNotFoundError(
                f"GraphRAG index directory not found: {index_path}"
            )

        # 强校验三张表都存在
        for fname in self.REQUIRED_FILES:
            fpath = os.path.join(index_path, fname)
            if not os.path.isfile(fpath):
                raise FileNotFoundError(
                    f"Required GraphRAG index file not found: {fpath}"
                )

        self.index_path: str = index_path
        logger.info(
            "GraphRAGBridge initialized with index_path=%s (pandas=%s, graphrag=%s)",
            index_path, HAS_PANDAS, HAS_GRAPHRAG
        )

    # ─── 内部 I/O ─────────────────────────────────────────────────

    def _read_parquet(self, file_name: str) -> "pd.DataFrame":
        """
        读取 parquet 文件。

        优先级：graphrag 官方 reader → pandas 直读。
        缺文件时抛 FileNotFoundError，不吞异常。

        Args:
            file_name: 文件名 (不含目录前缀)

        Returns:
            pd.DataFrame

        Raises:
            FileNotFoundError: 文件不存在
            RuntimeError: 读取失败 (文件损坏 / 权限不足)
        """
        file_path = os.path.join(self.index_path, file_name)
        if not os.path.isfile(file_path):
            raise FileNotFoundError(
                f"Required GraphRAG index file not found: {file_path}"
            )

        # 优先走 graphrag 官方 storage reader (如果有且暴露了公开 API)
        if HAS_GRAPHRAG:
            reader = self._try_graphrag_reader(file_path)
            if reader is not None:
                logger.debug("Read %s via graphrag official reader", file_name)
                return reader

        # 回退 pandas
        try:
            df = pd.read_parquet(file_path)
            logger.debug("Read %s via pandas (%d rows)", file_name, len(df))
            return df
        except ImportError as exc:
            raise ImportError(
                "Missing required dependency: pandas and pyarrow are needed "
                "to parse GraphRAG indices."
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Failed to read parquet file {file_path}: {exc}"
            ) from exc

    @staticmethod
    def _try_graphrag_reader(file_path: str) -> Optional["pd.DataFrame"]:
        """
        尝试使用 graphrag 官方 reader 读取 parquet。
        当前版本的 graphrag 底层仍然依赖 pandas，此处保留扩展点。

        Returns:
            DataFrame if successful, None otherwise.
        """
        try:
            # graphrag >= 2.x 暴露了 read_indexer_entities 等函数，
            # 但 API 不稳定，仅当确认有 parquet_file_reader 时才走此路径。
            from graphrag.index.storage import read_paraquet_file  # type: ignore[import-untyped]
            return read_paraquet_file(file_path)
        except (ImportError, AttributeError):
            return None

    # ─── 辅助工具 ──────────────────────────────────────────────────

    @staticmethod
    def _safe_str(value: Any) -> str:
        """安全转字符串，None / NaN 返回空串。"""
        if value is None:
            return ""
        if HAS_PANDAS and pd.isna(value):
            return ""
        return str(value)

    @staticmethod
    def _safe_list(value: Any) -> list:
        """
        将 parquet 中的列表字段归一化为 Python list。
        处理 JSON 字符串、逗号分隔字符串、numpy array 等各种格式。
        """
        if value is None:
            return []
        if HAS_PANDAS and pd.api.types.is_scalar(value) and pd.isna(value):
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, (set, tuple)):
            return list(value)
        # numpy array
        if hasattr(value, 'tolist'):
            return value.tolist()
        # JSON string: "[\"a\", \"b\"]"
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith('['):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
            # 逗号分隔回退
            if ',' in stripped:
                return [s.strip() for s in stripped.split(',') if s.strip()]
            return [stripped] if stripped else []
        return [value]

    # ─── 公开 API ──────────────────────────────────────────────────

    def get_global_communities(self, level: int = 1) -> List[Dict[str, Any]]:
        """
        获取指定层级的全局社区报告。

        读取 community_reports.parquet，按 ``level`` 列过滤后映射为标准字典列表。

        Args:
            level: 社区层级 (0 为顶层社区)。

        Returns:
            list[dict]，每项包含：
                community_id, title, summary, full_content, rank, weight,
                findings, level, source='graphrag'

        Raises:
            FileNotFoundError: parquet 缺失
            RuntimeError: 读取失败
        """
        assert isinstance(level, int) and level >= 0, (
            f"level must be a non-negative integer, got {level!r}"
        )

        logger.info(
            "Extracting global communities at level %d from: %s",
            level, self.index_path
        )

        df_reports = self._read_parquet(self.FILE_COMMUNITY_REPORTS)

        # 按 level 过滤
        if 'level' in df_reports.columns:
            df_filtered = df_reports[df_reports['level'] == level]
        else:
            logger.warning(
                "No 'level' column found in %s. Returning all %d rows unfiltered.",
                self.FILE_COMMUNITY_REPORTS, len(df_reports)
            )
            df_filtered = df_reports

        results: List[Dict[str, Any]] = []
        for item in df_filtered.to_dict(orient='records'):
            rank_val = item.get("rank", 0.0)
            results.append({
                "community_id": self._safe_str(
                    item.get("community", item.get("community_id", item.get("id", "")))
                ),
                "title": self._safe_str(item.get("title", "")),
                "summary": self._safe_str(item.get("summary", "")),
                "full_content": self._safe_str(
                    item.get("full_content", item.get("explanation", ""))
                ),
                "rank": float(rank_val) if rank_val is not None and not (HAS_PANDAS and pd.isna(rank_val)) else 0.0,
                "weight": float(item.get("weight", rank_val or 0.0)) if item.get("weight") is not None else float(rank_val or 0.0),
                "findings": self._safe_list(item.get("findings", [])),
                "level": int(item.get("level", level)),
                "source": "graphrag"
            })

        logger.info(
            "get_global_communities(level=%d): returned %d communities",
            level, len(results)
        )
        return results

    def get_entity_association(self, query: str) -> Dict[str, Any]:
        """
        查询实体关联图谱：对 query 做实体名/别名大小写无关匹配，
        通过 communities.parquet 的 entity_ids 反向关联 community_id，
        再联合 community_reports 返回完整关联结果。

        Args:
            query: 查询字符串（实体名或别名片段）

        Returns:
            dict 包含三个键：
                matched_entities:    list[dict]  — 命中的实体记录
                matched_communities: list[dict]  — 关联的社区记录
                matched_reports:     list[dict]  — 关联的社区报告

        Raises:
            FileNotFoundError: 三张 parquet 中任一缺失
            ValueError: query 为空
        """
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string.")

        query_lower = query.strip().lower()
        logger.info("Querying entity associations for: %r", query)

        # ── Step 1: 从 entities.parquet 做名称/别名匹配 ──
        df_entities = self._read_parquet(self.FILE_ENTITIES)

        mask = pd.Series(False, index=df_entities.index)

        if 'name' in df_entities.columns:
            mask = mask | (
                df_entities['name']
                .astype(str)
                .str.lower()
                .str.contains(query_lower, na=False, regex=False)
            )

        if 'aliases' in df_entities.columns:
            mask = mask | (
                df_entities['aliases']
                .astype(str)
                .str.lower()
                .str.contains(query_lower, na=False, regex=False)
            )

        # 追加 description 字段匹配以提高召回率
        if 'description' in df_entities.columns:
            mask = mask | (
                df_entities['description']
                .astype(str)
                .str.lower()
                .str.contains(query_lower, na=False, regex=False)
            )

        matched_entities = df_entities[mask].to_dict(orient='records')
        matched_entity_ids: Set[str] = {
            self._safe_str(e.get('id', e.get('name', '')))
            for e in matched_entities
        }

        logger.info(
            "Entity match: %d entities matched for query=%r",
            len(matched_entities), query
        )

        # ── Step 2: 通过 communities.parquet 的 entity_ids 反向关联 ──
        df_communities = self._read_parquet(self.FILE_COMMUNITIES)
        community_ids: Set[str] = set()

        # 策略 A: 实体表自身有 community_ids 字段 (部分 graphrag 版本)
        for ent in matched_entities:
            raw_cids = ent.get("community_ids", None)
            if raw_cids is not None:
                for cid in self._safe_list(raw_cids):
                    cid_str = self._safe_str(cid)
                    if cid_str:
                        community_ids.add(cid_str)

        # 策略 B: 标准 GraphRAG schema — communities 表的 entity_ids 列
        if 'entity_ids' in df_communities.columns and matched_entity_ids:
            for _, row in df_communities.iterrows():
                ent_ids_in_community = self._safe_list(row.get('entity_ids'))
                ent_ids_str = {self._safe_str(x) for x in ent_ids_in_community}
                if ent_ids_str & matched_entity_ids:
                    community_col_val = self._safe_str(
                        row.get('community', row.get('id', ''))
                    )
                    if community_col_val:
                        community_ids.add(community_col_val)

        # 过滤社区表
        if community_ids:
            community_id_col = 'community' if 'community' in df_communities.columns else 'id'
            if community_id_col in df_communities.columns:
                matched_communities = df_communities[
                    df_communities[community_id_col].astype(str).isin(community_ids)
                ].to_dict(orient='records')
            else:
                matched_communities = []
        else:
            matched_communities = []

        # ── Step 3: 关联 community_reports ──
        df_reports = self._read_parquet(self.FILE_COMMUNITY_REPORTS)
        if community_ids:
            report_col = 'community' if 'community' in df_reports.columns else 'community_id'
            if report_col in df_reports.columns:
                matched_reports = df_reports[
                    df_reports[report_col].astype(str).isin(community_ids)
                ].to_dict(orient='records')
            else:
                matched_reports = []
        else:
            matched_reports = []

        logger.info(
            "Entity association result: entities=%d, communities=%d, reports=%d",
            len(matched_entities), len(matched_communities), len(matched_reports)
        )

        return {
            "matched_entities": matched_entities,
            "matched_communities": matched_communities,
            "matched_reports": matched_reports
        }


# ═══════════════════════════════════════════════════════════════════
# 最小验收测试 — python -m layers.g_synthesis_graphrag_bridge
# ═══════════════════════════════════════════════════════════════════
def _run_acceptance_test() -> None:
    """
    最小验收测试：
    1. 在临时目录创建三张 parquet
    2. 验证 level 过滤
    3. 验证实体命中后能关联回 community_report
    """
    import tempfile
    import shutil

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    tmpdir = tempfile.mkdtemp(prefix="graphrag_bridge_test_")
    print(f"[TEST] 临时测试目录: {tmpdir}")

    try:
        # ── 构造测试数据 ──
        # entities.parquet
        df_entities = pd.DataFrame([
            {"id": "ent_001", "name": "Laser Power", "type": "parameter",
             "description": "激光功率参数", "text_unit_ids": "[]"},
            {"id": "ent_002", "name": "Nitrogen Transport", "type": "phenomenon",
             "description": "氮传输现象", "text_unit_ids": "[]"},
            {"id": "ent_003", "name": "Cooling Rate", "type": "parameter",
             "description": "冷却速率", "text_unit_ids": "[]"},
        ])
        df_entities.to_parquet(os.path.join(tmpdir, "entities.parquet"))

        # communities.parquet
        df_communities = pd.DataFrame([
            {"id": "comm_A", "community": "0", "level": 0, "title": "Top Community",
             "entity_ids": '["ent_001", "ent_002"]', "size": 2},
            {"id": "comm_B", "community": "1", "level": 1, "title": "Sub Community B",
             "entity_ids": '["ent_002", "ent_003"]', "size": 2},
            {"id": "comm_C", "community": "2", "level": 1, "title": "Sub Community C",
             "entity_ids": '["ent_001"]', "size": 1},
        ])
        df_communities.to_parquet(os.path.join(tmpdir, "communities.parquet"))

        # community_reports.parquet
        df_reports = pd.DataFrame([
            {"id": "rpt_A", "community": "0", "level": 0, "title": "Top Level Report",
             "summary": "全局概览", "full_content": "全局分析内容...",
             "rank": 1.0, "findings": '["Finding A1", "Finding A2"]'},
            {"id": "rpt_B", "community": "1", "level": 1, "title": "Report B",
             "summary": "氮传输与冷却", "full_content": "氮传输详细分析...",
             "rank": 0.8, "findings": '["Finding B1"]'},
            {"id": "rpt_C", "community": "2", "level": 1, "title": "Report C",
             "summary": "激光功率", "full_content": "激光功率详细分析...",
             "rank": 0.6, "findings": '["Finding C1"]'},
        ])
        df_reports.to_parquet(os.path.join(tmpdir, "community_reports.parquet"))

        # ── 初始化 Bridge ──
        bridge = GraphRAGBridge(index_path=tmpdir)
        print("[TEST] [PASS] GraphRAGBridge initialized")

        # ── 测试 1: level 过滤 ──
        level0 = bridge.get_global_communities(level=0)
        level1 = bridge.get_global_communities(level=1)
        assert len(level0) == 1, f"Expected 1 community at level 0, got {len(level0)}"
        assert level0[0]["community_id"] == "0", f"Expected community_id='0', got {level0[0]['community_id']}"
        assert level0[0]["source"] == "graphrag"
        assert len(level1) == 2, f"Expected 2 communities at level 1, got {len(level1)}"
        print(f"[TEST] [PASS] Level filter: level=0 -> {len(level0)}, level=1 -> {len(level1)}")

        # 验证字段完整性
        required_fields = {"community_id", "title", "summary", "full_content",
                           "rank", "weight", "findings", "level", "source"}
        for item in level0 + level1:
            missing = required_fields - set(item.keys())
            assert not missing, f"Missing fields: {missing}"
        print("[TEST] [PASS] Output field completeness OK")

        # ── 测试 2: 实体关联 ──
        result = bridge.get_entity_association("Nitrogen")
        assert len(result["matched_entities"]) >= 1, "Should match at least 1 entity"
        assert len(result["matched_reports"]) >= 1, "Should match at least 1 report via community"
        print(f"[TEST] [PASS] Entity association: entities={len(result['matched_entities'])}, "
              f"communities={len(result['matched_communities'])}, "
              f"reports={len(result['matched_reports'])}")

        # 测试大小写无关
        result_lower = bridge.get_entity_association("laser power")
        assert len(result_lower["matched_entities"]) >= 1, "Case-insensitive match failed"
        print("[TEST] [PASS] Case-insensitive match OK")

        # ── 测试 3: 空查询应抛异常 ──
        try:
            bridge.get_entity_association("")
            assert False, "Should have raised ValueError"
        except ValueError:
            print("[TEST] [PASS] Empty query ValueError OK")

        print("\n" + "=" * 60)
        print("[TEST] ALL PASSED - Acceptance test complete!")
        print("=" * 60)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        print(f"[TEST] 临时目录已清理: {tmpdir}")


if __name__ == "__main__":
    _run_acceptance_test()
