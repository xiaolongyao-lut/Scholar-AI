# test_p3_exporter.py
# P3 导出器回归测试 — 覆盖 Step 3 全部场景:
#   正常 DAG、特殊字符/单引号、自环、环路、空图、helper 行为

import json
import pytest
from layers.p3_exporter import KnowledgeGraphExporter


# ============================================================
#  fixtures
# ============================================================


@pytest.fixture
def exporter() -> KnowledgeGraphExporter:
    return KnowledgeGraphExporter()


@pytest.fixture
def normal_dag() -> dict:
    """正常的 DAG，2 个节点，1 条边。"""
    return {
        "nodes": [{"id": "LaserPower"}, {"id": "MeltDepth"}],
        "links": [
            {"source": "LaserPower", "target": "MeltDepth", "relation": "Increases", "confidence": 0.95}
        ],
    }


@pytest.fixture
def multi_chain_dag() -> dict:
    """正常的多链 DAG：A→B→C + A→D。"""
    return {
        "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}],
        "links": [
            {"source": "A", "target": "B", "relation": "causes", "confidence": 0.9},
            {"source": "B", "target": "C", "relation": "leads_to", "confidence": 0.85},
            {"source": "A", "target": "D", "relation": "triggers", "confidence": 0.8},
        ],
    }


@pytest.fixture
def special_char_dag() -> dict:
    """包含单引号、中文、特殊字符的节点名和关系名。"""
    return {
        "nodes": [{"id": "O'Brien's Laser"}, {"id": "激光功率 (kW)"}],
        "links": [
            {
                "source": "O'Brien's Laser",
                "target": "激光功率 (kW)",
                "relation": "提高-产出@v2",
                "confidence": 0.88,
            }
        ],
    }


@pytest.fixture
def self_loop_dag() -> dict:
    """自环 DAG — 应被拦截。"""
    return {
        "nodes": [{"id": "X"}],
        "links": [
            {"source": "X", "target": "X", "relation": "selfRef", "confidence": 0.5}
        ],
    }


@pytest.fixture
def cycle_dag() -> dict:
    """环路 DAG — 应被拦截。"""
    return {
        "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
        "links": [
            {"source": "A", "target": "B", "relation": "r1", "confidence": 0.9},
            {"source": "B", "target": "C", "relation": "r2", "confidence": 0.85},
            {"source": "C", "target": "A", "relation": "r3", "confidence": 0.8},
        ],
    }


@pytest.fixture
def empty_dag() -> dict:
    """空图 — 应能正常输出空结果。"""
    return {"nodes": [], "links": []}


# ============================================================
#  Helper 单元测试
# ============================================================


class TestCypherHelpers:
    """_escape_cypher_string / _sanitize_cypher_identifier。"""

    def test_escape_single_quote(self, exporter: KnowledgeGraphExporter) -> None:
        assert exporter._escape_cypher_string("O'Brien") == "O''Brien"

    def test_escape_double_single_quote(self, exporter: KnowledgeGraphExporter) -> None:
        assert exporter._escape_cypher_string("it''s") == "it''''s"

    def test_escape_no_special(self, exporter: KnowledgeGraphExporter) -> None:
        assert exporter._escape_cypher_string("LaserPower") == "LaserPower"

    def test_sanitize_identifier_spaces(self, exporter: KnowledgeGraphExporter) -> None:
        result = exporter._sanitize_cypher_identifier("Laser Power")
        assert " " not in result
        assert result == "Laser_Power"

    def test_sanitize_identifier_leading_digit(self, exporter: KnowledgeGraphExporter) -> None:
        result = exporter._sanitize_cypher_identifier("3DPrint")
        assert result[0] == "_"

    def test_sanitize_identifier_empty_raises(self, exporter: KnowledgeGraphExporter) -> None:
        with pytest.raises(ValueError):
            exporter._sanitize_cypher_identifier("   ")

    def test_sanitize_identifier_special_chars(self, exporter: KnowledgeGraphExporter) -> None:
        result = exporter._sanitize_cypher_identifier("提高-产出@v2")
        # 应只保留字母、数字、下划线
        assert all(ch.isalnum() or ch == "_" for ch in result)
        assert len(result) > 0


class TestRdfHelpers:
    """_sanitize_rdf_local_name。"""

    def test_rdf_local_name_basic(self, exporter: KnowledgeGraphExporter) -> None:
        result = exporter._sanitize_rdf_local_name("Laser-Power")
        assert result == "Laser_Power"

    def test_rdf_local_name_special(self, exporter: KnowledgeGraphExporter) -> None:
        result = exporter._sanitize_rdf_local_name("O'Brien")
        assert "'" not in result

    def test_rdf_local_name_leading_digit(self, exporter: KnowledgeGraphExporter) -> None:
        result = exporter._sanitize_rdf_local_name("42things")
        assert result.startswith("_")

    def test_rdf_local_name_empty_raises(self, exporter: KnowledgeGraphExporter) -> None:
        with pytest.raises(ValueError):
            exporter._sanitize_rdf_local_name("@#$%")


class TestCycleDetection:
    """_detect_cycles / _validate_dag。"""

    def test_no_cycle_normal(self, exporter: KnowledgeGraphExporter, normal_dag: dict) -> None:
        has_cycle, msg = exporter._detect_cycles(normal_dag)
        assert has_cycle is False
        assert msg == ""

    def test_self_loop_detected(self, exporter: KnowledgeGraphExporter, self_loop_dag: dict) -> None:
        has_cycle, msg = exporter._detect_cycles(self_loop_dag)
        assert has_cycle is True
        assert "自环" in msg

    def test_cycle_detected(self, exporter: KnowledgeGraphExporter, cycle_dag: dict) -> None:
        has_cycle, msg = exporter._detect_cycles(cycle_dag)
        assert has_cycle is True

    def test_validate_dag_raises_on_cycle(self, exporter: KnowledgeGraphExporter, cycle_dag: dict) -> None:
        with pytest.raises(ValueError, match="循环"):
            exporter._validate_dag(cycle_dag)

    def test_validate_dag_raises_on_self_loop(self, exporter: KnowledgeGraphExporter, self_loop_dag: dict) -> None:
        with pytest.raises(ValueError, match="自环"):
            exporter._validate_dag(self_loop_dag)

    def test_empty_dag_no_cycle(self, exporter: KnowledgeGraphExporter, empty_dag: dict) -> None:
        has_cycle, msg = exporter._detect_cycles(empty_dag)
        assert has_cycle is False


# ============================================================
#  Cypher 导出测试
# ============================================================


class TestExportCypher:
    """export_to_cypher 场景覆盖。"""

    def test_normal_dag_cypher(self, exporter: KnowledgeGraphExporter, normal_dag: dict) -> None:
        stmts = exporter.export_to_cypher(normal_dag)
        assert isinstance(stmts, list)
        assert len(stmts) >= 2  # 至少 MERGE 节点 + CREATE 边
        merge_stmts = [s for s in stmts if s.startswith("MERGE")]
        create_stmts = [s for s in stmts if "CREATE" in s]
        assert len(merge_stmts) == 2
        assert len(create_stmts) == 1
        # 边语句包含 CAUSES
        assert ":CAUSES" in create_stmts[0]

    def test_multi_chain_dag_cypher(self, exporter: KnowledgeGraphExporter, multi_chain_dag: dict) -> None:
        stmts = exporter.export_to_cypher(multi_chain_dag)
        merge_stmts = [s for s in stmts if s.startswith("MERGE")]
        create_stmts = [s for s in stmts if "CREATE" in s]
        assert len(merge_stmts) == 4  # A, B, C, D
        assert len(create_stmts) == 3

    def test_special_char_dag_cypher(self, exporter: KnowledgeGraphExporter, special_char_dag: dict) -> None:
        stmts = exporter.export_to_cypher(special_char_dag)
        # 单引号必须被正确转义
        cypher_text = "\n".join(stmts)
        # "O'Brien's Laser" 的单引号应被转义为 ''
        assert "O''Brien''s Laser" in cypher_text
        assert len(stmts) >= 2

    def test_self_loop_dag_raises(self, exporter: KnowledgeGraphExporter, self_loop_dag: dict) -> None:
        with pytest.raises(ValueError, match="自环"):
            exporter.export_to_cypher(self_loop_dag)

    def test_cycle_dag_raises(self, exporter: KnowledgeGraphExporter, cycle_dag: dict) -> None:
        with pytest.raises(ValueError, match="循环"):
            exporter.export_to_cypher(cycle_dag)

    def test_empty_dag_cypher(self, exporter: KnowledgeGraphExporter, empty_dag: dict) -> None:
        stmts = exporter.export_to_cypher(empty_dag)
        assert stmts == []  # 空图返回空列表


# ============================================================
#  TTL 导出测试
# ============================================================


class TestExportTtl:
    """export_to_ttl 场景覆盖。"""

    def test_normal_dag_ttl(self, exporter: KnowledgeGraphExporter, normal_dag: dict) -> None:
        ttl = exporter.export_to_ttl(normal_dag)
        assert "welding:" in ttl
        assert "xsd:float" in ttl
        assert "LaserPower" in ttl
        assert "MeltDepth" in ttl

    def test_special_char_dag_ttl(self, exporter: KnowledgeGraphExporter, special_char_dag: dict) -> None:
        ttl = exporter.export_to_ttl(special_char_dag)
        # 特殊字符必须被清洗
        assert "'" not in ttl.split("@prefix")[1] if "@prefix" in ttl else True
        # 必须包含规整后的标识符
        assert "welding:" in ttl

    def test_self_loop_dag_raises(self, exporter: KnowledgeGraphExporter, self_loop_dag: dict) -> None:
        with pytest.raises(ValueError, match="自环"):
            exporter.export_to_ttl(self_loop_dag)

    def test_cycle_dag_raises(self, exporter: KnowledgeGraphExporter, cycle_dag: dict) -> None:
        with pytest.raises(ValueError, match="循环"):
            exporter.export_to_ttl(cycle_dag)

    def test_empty_dag_ttl(self, exporter: KnowledgeGraphExporter, empty_dag: dict) -> None:
        ttl = exporter.export_to_ttl(empty_dag)
        # 空图只输出 prefix 行
        assert "@prefix welding:" in ttl
        # 不应有 triple 行
        lines = [ln.strip() for ln in ttl.split("\n") if ln.strip() and not ln.strip().startswith("@prefix")]
        assert len(lines) == 0


# ============================================================
#  JSON-LD 导出测试
# ============================================================


class TestExportJsonld:
    """export_to_jsonld 场景覆盖。"""

    def test_normal_dag_jsonld(self, exporter: KnowledgeGraphExporter, normal_dag: dict) -> None:
        result = exporter.export_to_jsonld(normal_dag)
        data = json.loads(result)
        assert "@context" in data
        assert "@graph" in data
        assert len(data["@graph"]) == 1
        assert data["@graph"][0]["@type"] == "CausalRelation"

    def test_multi_chain_jsonld(self, exporter: KnowledgeGraphExporter, multi_chain_dag: dict) -> None:
        result = exporter.export_to_jsonld(multi_chain_dag)
        data = json.loads(result)
        assert len(data["@graph"]) == 3

    def test_self_loop_raises(self, exporter: KnowledgeGraphExporter, self_loop_dag: dict) -> None:
        with pytest.raises(ValueError, match="自环"):
            exporter.export_to_jsonld(self_loop_dag)

    def test_cycle_raises(self, exporter: KnowledgeGraphExporter, cycle_dag: dict) -> None:
        with pytest.raises(ValueError, match="循环"):
            exporter.export_to_jsonld(cycle_dag)

    def test_empty_dag_jsonld(self, exporter: KnowledgeGraphExporter, empty_dag: dict) -> None:
        result = exporter.export_to_jsonld(empty_dag)
        data = json.loads(result)
        assert data["@graph"] == []
