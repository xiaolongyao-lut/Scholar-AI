import json
import re
from typing import List, Dict, Any


class KnowledgeGraphExporter:
    """
    P3 能力 9: 知识图谱导出 (RDF/Cypher/JSON-LD)
    """

    def _escape_cypher_string(self, value: Any) -> str:
        """转义 Cypher 字符串字面量。"""
        return str(value).replace("'", "''")

    def _sanitize_cypher_identifier(self, value: Any) -> str:
        """将任意文本规整为安全的 Cypher 标识符。"""
        text = str(value).strip().replace("-", "_").replace(" ", "_")
        text = re.sub(r"[^0-9A-Za-z_]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        if not text:
            raise ValueError("无效的 Cypher 标识符")
        if text[0].isdigit():
            text = f"_{text}"
        return text

    def _sanitize_rdf_local_name(self, value: Any) -> str:
        """将任意文本规整为安全的 RDF local name。"""
        text = str(value).strip().replace("-", "_").replace(" ", "_")
        text = re.sub(r"[^0-9A-Za-z_]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        if not text:
            raise ValueError("无效的 RDF 本地名")
        if text[0].isdigit():
            text = f"_{text}"
        return text

    def _detect_cycles(self, dag_data: Dict[str, Any]) -> tuple[bool, str]:
        """检测 DAG 是否包含自环或环路。"""
        adjacency: Dict[str, List[str]] = {}
        vertices = set()

        for link in dag_data.get("links", []):
            source = str(link.get("source", "")).strip()
            target = str(link.get("target", "")).strip()
            if not source or not target:
                raise ValueError("DAG 链接缺少 source 或 target")

            vertices.add(source)
            vertices.add(target)
            adjacency.setdefault(source, []).append(target)

            if source == target:
                return True, f"自环检测: {source} -> {target}"

        visited = set()
        recursion_stack = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            recursion_stack.add(node)

            for neighbor in adjacency.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in recursion_stack:
                    return True

            recursion_stack.remove(node)
            return False

        for node in vertices:
            if node not in visited and dfs(node):
                return True, f"循环依赖检测: 在节点 {node} 处发现循环"

        return False, ""

    def _validate_dag(self, dag_data: Dict[str, Any]) -> None:
        has_cycle, cycle_message = self._detect_cycles(dag_data)
        if has_cycle:
            raise ValueError(f"无法导出包含循环的 DAG: {cycle_message}")

    def export_to_jsonld(self, dag_data: Dict[str, Any]) -> str:
        """
        导出为 JSON-LD 格式
        """
        self._validate_dag(dag_data)

        context = {
            "welding": "http://welding.knowledge.org/",
            "source": "welding:source_node",
            "target": "welding:target_node",
            "relation": "welding:predicate",
            "confidence": "welding:confidence"
        }

        graph = []
        for link in dag_data.get("links", []):
            graph.append({
                "@type": "CausalRelation",
                "source": link["source"],
                "target": link["target"],
                "relation": link["relation"],
                "confidence": link["confidence"]
            })

        return json.dumps({"@context": context, "@graph": graph}, indent=2, ensure_ascii=False)

    def export_to_cypher(self, dag_data: Dict[str, Any]) -> List[str]:
        """
        导出为 Neo4j Cypher 脚本
        """
        self._validate_dag(dag_data)

        statements = []
        seen_nodes = set()
        node_ids: List[str] = []

        # 创建节点：优先使用 nodes，再补充 links 中出现但 nodes 中缺失的端点
        for node in dag_data.get("nodes", []):
            node_id = node.get("id") if isinstance(node, dict) else str(node)
            if node_id is None:
                continue
            node_id = str(node_id).strip()
            if node_id and node_id not in seen_nodes:
                seen_nodes.add(node_id)
                node_ids.append(node_id)

        for link in dag_data.get("links", []):
            for endpoint in (link.get("source"), link.get("target")):
                if endpoint is None:
                    continue
                endpoint = str(endpoint).strip()
                if endpoint and endpoint not in seen_nodes:
                    seen_nodes.add(endpoint)
                    node_ids.append(endpoint)

        for node_id in node_ids:
            safe_name = self._escape_cypher_string(node_id)
            statements.append(f"MERGE (n:Param {{name: '{safe_name}'}})")

        # 创建边
        for link in dag_data.get("links", []):
            source = str(link["source"]).strip()
            target = str(link["target"]).strip()
            relation = str(link["relation"]).strip()
            safe_source = self._escape_cypher_string(source)
            safe_target = self._escape_cypher_string(target)
            confidence = float(link["confidence"])

            statements.append(
                f"MATCH (a:Param {{name: '{safe_source}'}}), (b:Param {{name: '{safe_target}'}}) "
                f"CREATE (a)-[:CAUSES {{predicate: '{self._escape_cypher_string(relation)}', confidence: {confidence}}}]->(b)"
            )

        return statements

    def export_to_ttl(self, dag_data: Dict[str, Any]) -> str:
        """
        导出为 RDF Turtle 格式 (安全规范版本)
        """
        self._validate_dag(dag_data)

        ttl_lines = [
            "@prefix welding: <http://welding.knowledge.org/> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            ""
        ]

        for link in dag_data.get("links", []):
            source = self._sanitize_rdf_local_name(link["source"])
            target = self._sanitize_rdf_local_name(link["target"])
            relation = self._sanitize_rdf_local_name(link["relation"])
            confidence = float(link["confidence"])
            ttl_lines.append(f"welding:{source} welding:{relation} welding:{target} ;")
            ttl_lines.append(f"    welding:confidence {confidence}^^xsd:float .")

        return "\n".join(ttl_lines)
