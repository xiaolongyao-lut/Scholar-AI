import logging
from collections import defaultdict
from typing import List, Dict, Any, Tuple, Set
from pydantic import BaseModel

logger = logging.getLogger("P3_CausalEngine")

class CausalChain(BaseModel):
    """因果链路模型"""
    nodes: List[str]
    relations: List[str]
    confidence: float
    evidence_count: int

class CausalEngine:
    """
    P3 能力 2 & 5: 因果链路提取与 DAG 构建
    """

    def __init__(self, max_depth: int = 6):
        self.max_depth = max_depth

    def extract_chains(self, triplets: List[Tuple[str, str, str]]) -> List[CausalChain]:
        """
        从三元组集合中提取因果链
        """
        # 1. 构建图结构 nodes -> [(next_node, predicate)]
        graph = defaultdict(list)
        for s, p, o in triplets:
            graph[s].append((o, p))

        # 2. 识别源节点 (无入边的节点) 用于起始探索
        # 简化处理：从所有节点尝试 DFS
        all_chains = []
        for start_node in list(graph.keys()):
            paths = self._dfs_explore(start_node, graph, current_path=[], current_relations=[], depth=0)
            for nodes, rels in paths:
                if len(nodes) > 1:
                    conf = self._calculate_chain_confidence(len(nodes))
                    all_chains.append(CausalChain(
                        nodes=nodes,
                        relations=rels,
                        confidence=conf,
                        evidence_count=len(rels)
                    ))
        
        return all_chains

    def _dfs_explore(self, current_node: str, graph: Dict, 
                     current_path: List[str], current_relations: List[str], 
                     depth: int) -> List[Tuple[List[str], List[str]]]:
        """
        深度优先搜索提取路径
        """
        new_path = current_path + [current_node]
        
        if depth >= self.max_depth or current_node not in graph:
            return [(new_path, current_relations)]

        results = []
        found_neighbors = False
        for next_node, pred in graph[current_node]:
            # 避免环路：新节点不在当前路径中
            if next_node not in new_path:
                found_neighbors = True
                results.extend(self._dfs_explore(
                    next_node, graph, new_path, 
                    current_relations + [pred], depth + 1
                ))
        
        if not found_neighbors:
            return [(new_path, current_relations)]
            
        return results

    def _calculate_chain_confidence(self, length: int) -> float:
        """
        计算链路置信度 (P3 设计逻辑: 随长度衰减)
        """
        if length <= 2: return 0.95
        return round(0.95 ** (length - 1), 3)

    def build_inference_dag(self, chains: List[CausalChain]) -> Dict[str, Any]:
        """
        将链聚合成最终的 DAG 展示结构
        """
        nodes_set = set()
        edges = []
        
        for chain in chains:
            for node in chain.nodes:
                nodes_set.add(node)
            
            for i in range(len(chain.nodes) - 1):
                edges.append({
                    "source": chain.nodes[i],
                    "target": chain.nodes[i+1],
                    "relation": chain.relations[i],
                    "confidence": chain.confidence
                })
        
        return {
            "nodes": [{"id": n} for n in nodes_set],
            "links": edges
        }
