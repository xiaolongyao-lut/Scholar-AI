import json
from typing import List, Dict, Any
from layers.p3_causal_engine import CausalChain

class KnowledgeGraphExporter:
    """
    P3 能力 9: 知识图谱导出 (RDF/Cypher/JSON-LD)
    """

    def export_to_jsonld(self, dag_data: Dict[str, Any]) -> str:
        """
        导出为 JSON-LD 格式
        """
        context = {
            "welding": "http://welding.knowledge.org/",
            "source": "welding:source_node",
            "target": "welding:target_node",
            "relation": "welding:predicate",
            "confidence": "welding:confidence"
        }
        
        graph = []
        for link in dag_data.get('links', []):
            graph.append({
                "@type": "CausalRelation",
                "source": link['source'],
                "target": link['target'],
                "relation": link['relation'],
                "confidence": link['confidence']
            })
            
        return json.dumps({"@context": context, "@graph": graph}, indent=2, ensure_ascii=False)

    def export_to_cypher(self, dag_data: Dict[str, Any]) -> List[str]:
        """
        导出为 Neo4j Cypher 脚本
        """
        statements = []
        # 创建节点
        for node in dag_data.get('nodes', []):
            label = node['id'].replace(" ", "_").replace("-", "_")
            statements.append(f"MERGE (n:Param {{name: '{node['id']}'}})")
            
        # 创建边
        for link in dag_data.get('links', []):
            s = link['source']
            t = link['target']
            rel = link['relation']
            statements.append(
                f"MATCH (a:Param {{name: '{s}'}}), (b:Param {{name: '{t}'}}) "
                f"CREATE (a)-[:CAUSES {{predicate: '{rel}', confidence: {link['confidence']}}}]->(b)"
            )
            
        return statements

    def export_to_ttl(self, dag_data: Dict[str, Any]) -> str:
        """
        导出为 RDF Turtle 格式 (简易模版)
        """
        ttl_lines = [
            "@prefix welding: <http://welding.knowledge.org/> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            ""
        ]
        
        for link in dag_data.get('links', []):
            s = link['source'].replace(" ", "_")
            t = link['target'].replace(" ", "_")
            rel = link['relation']
            ttl_lines.append(f"welding:{s} welding:{rel} welding:{t} ;")
            ttl_lines.append(f"    welding:confidence {link['confidence']}^^xsd:float .")
            
        return "\n".join(ttl_lines)
