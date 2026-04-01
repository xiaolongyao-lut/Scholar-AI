from __future__ import annotations

import re
import math
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .ai_adapter import AIAdapter

EN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-']+")
CN_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
SENT_SPLIT_RE = re.compile(r'(?<=[\.!?。；;])\s+')
NUMERIC_RE = re.compile(r'\b\d+(?:\.\d+)?(?:\s*(?:%|wt\.%|at\.%|μm|µm|mm|nm|kW|W|Hz|MPa|HV|J/mm|L/min|°C|K|min|s|epoch))?\b', re.I)
CITATION_RE = re.compile(r'\[(?:\d+[\-–,\s]*)+\]|\b\d{1,3}\b(?=\s*(?:,|\.|\)|\]))')

STOPWORDS = {
    'the','and','for','with','that','this','from','were','was','are','into','under','than','when','where','while','been','their','which',
    'using','used','study','results','result','paper','article','analysis','different','effect','effects','based','shown','show','shows','figure',
    'table','weld','laser','steel','alloy','material','materials','sample','samples','data','method','methods','process','processed',
    'significant','significantly','provide','provides','revealed','reveal','found','indicate','indicates','performed','page','journal'
}

GOAL_MAP = {
    '工艺参数': ['parameter', 'parameters', 'power', 'speed', 'frequency', 'heat input', 'composition', 'ratio', 'modulation', 'welding direction'],
    '熔池流动': ['molten pool', 'flow', 'convection', 'dynamics', 'keyhole', 'spatter'],
    '氮传输': ['nitrogen', 'nitriding', 'nitride', 'tin', 'transfer', 'transport'],
    '组织': ['microstructure', 'grain', 'phase', 'precipitate', 'texture', 'dendrite', 'equiaxed', 'columnar'],
    '应力': ['stress', 'residual stress', 'tensile', 'compressive'],
    '性能': ['hardness', 'wear', 'corrosion', 'tensile', 'mechanical', 'friction', 'performance', 'accuracy'],
    '裂纹': ['crack', 'cracks', 'cracking', 'recognition', 'defect', 'anomaly'],
    '图像': ['image', 'images', 'patch', 'augmentation', 'cnn', 'deep learning', 'transfer learning', 'dataset'],
    '增材制造': ['additive manufacturing', 'AM', 'DED', 'LPBF', 'powder bed fusion'],
    '柱状晶': ['columnar'],
    '等轴晶': ['equiaxed'],
    '成分判据': ['composition', 'compositional', 'criteria', 'criterion', 'p', 'q', 'Δts', 'constitutional supercooling'],
    '强化机制': ['strengthening', 'dislocation', 'solid-solution', 'grain refinement', 'hardness', 'precipitate'],
    '焊接方向': ['welding direction', 'direction', 'build direction', 'scanning direction'],
    '热输入': ['heat input', 'current', 'voltage', 'welding speed', 'cooling rate'],
}

METHOD_CUES = re.compile(r'\b(method|methods|experimental|procedure|performed|used|employed|prepared|processed|measured|characterized|test|tests|model|simulation|set to|parameters?|dataset|training|epoch|optimizer|batch size)\b', re.I)
RESULT_CUES = re.compile(r'\b(increase(?:d|s)?|decrease(?:d|s|tion)?|reduce(?:d|s|tion)?|improv(?:e|ed|es|ement)|enhanc(?:e|ed|es|ement)|achiev(?:e|ed|es)|yield(?:ed|s)?|accuracy|hardness|wear|tensile|fraction|size|width|depth|profile|transformed|coarsen(?:ed|ing)?|refined?|dominant|higher|lower|best|greater|smaller|finer|stronger|weaker|promoted|suppressed)\b', re.I)
MECH_CUES = re.compile(r'\b(because|due to|lead(?:s|ing)? to|result(?:ed)? in|promot(?:e|ed|es)|suppress(?:ed|es)?|mechanism|attribute(?:d)? to|therefore|thus|closely related|governed by|dominated by|caused by|originates from|facilitates?)\b', re.I)
BACKGROUND_CUES = re.compile(r'\b(challenge|however|traditionally|previous|recent studies|long-standing|review|introduction|remains unclear|is well established)\b', re.I)
HEDGE_CUES = re.compile(r'\b(may|might|could|suggest(?:s|ed)?|likely|appears? to|potentially|indicates?)\b', re.I)
META_CUES = re.compile(r'\b(fig\.?|figure|table)\s*\d+|\b(shown|listed|given|depicted|illustrated|summarized)\b', re.I)
HARDWARE_CUES = re.compile(r'\b(gpu|cpu|ram|nvidia|geforce|software|matlab|python|workstation|accelerate the model training)\b', re.I)
AFFILIATION_CUES = re.compile(r'\b(university|laboratory|department|school of|institute|china|uk|usa|available online|corresponding author|journal homepage|doi\.org)\b', re.I)
TITLE_AUTHORISH_CUES = re.compile(r'\b(research article|deep learning and image data-based|yaxing tong|results in engineering|nature communications|microstructural evolution)\b', re.I)
PARAMETER_TERM_RE = re.compile(r'\b(power|speed|velocity|frequency|radius|diameter|thickness|flow rate|gas flow|amplitude|modulation|offset|defocus|current|voltage|pressure|temperature|time|duration|scan|scanning|composition|content|batch size|optimizer|epoch)\b', re.I)
COMPARISON_CUE_RE = re.compile(r'\b(compared with|compared to|than|versus|whereas|higher|lower|greater|smaller|better|worse|best)\b', re.I)
CURRENT_WORK_CUES = re.compile(r'\b(this study|this work|our study|our work|herein|in this work|present work|we show|we demonstrate|we find|we observe|our results|in this study|the present study)\b', re.I)
LITERATURE_CUES = re.compile(r'\b(et al\.?|previous studies|reported|introduced|review|recent studies|widely used|generally associated|ImageNet|ILSVRC|challenge|Tan et al|according to .* et al)\b', re.I)
PROXY_BACKGROUND_CUES = re.compile(r'\b(used as a proxy|generally associated|widely used|according to|as listed and imaged by)\b', re.I)
RESULT_SECTION_CUES = re.compile(r'\b(result|discussion|conclusion)\b', re.I)
GENERIC_STATEMENT_CUES = re.compile(r'\b(generally|is considered|there are many examples|can be defined as|is defined as|is used as a proxy|models size, depth and parameters are given|according to the international standard)\b', re.I)
VISUAL_DESCRIPTION_CUES = re.compile(r'\b(image|micrograph|bse|ebsd|om image|sem image|maps?|schematic|depicts|illustrates?|optical microscopy|backscattered electron)\b', re.I)
FORMULA_EXPOSITION_CUES = re.compile(r'\b(equation|rosenthal|calculated using|represented as|where\s+[A-Za-zα-ωΑ-Ω]\s+(?:represents|is)|thermal diffusivity|empirical)\b', re.I)
CAPTIONISH_CUES = re.compile(r'\b(presents? the overall morpholog|depicts?|illustrates?|marked by|shows? the traced|image depicts|backscattered electron|ebsd map|optical micrograph|schematic diagram)\b', re.I)
PANEL_PREFIX_CUES = re.compile(r'^\s*(?:[a-z]\s+)?(?:\d+\([a-z0-9\-]+\)|\([a-z0-9\-]+\))(?:\s*,\s*\([a-z0-9\-]+\))*', re.I)
LEGENDISH_CUES = re.compile(r'\b(the shading in|dark grey|light grey|corresponding to columnar|corresponding to .* equiaxed|indicates the regions of)\b', re.I)
MODEL_REFERENCE_CUES = re.compile(r'\b(hunt\s+cet\s+model|hunt\s+model|cet\s+model|criterion|criteria|model\s*17|model\s*suggested|model\s*predicts?)\b', re.I)
DEFINITION_HEAVY_CUES = re.compile(r'\b(generally|typically|is considered\s+equiaxed|is considered\s+columnar|can be defined as|is defined as|is likely to be\s+(?:equiaxed|columnar)|serves as a criterion|used as a criterion)\b', re.I)
METHOD_LISTING_CUES = re.compile(r'\b(samples? were produced using|laser power of|scan speed of|spot size of|batch size of|optimizer was|epochs? of|using a laser power|using .* scan speed|step sizes? of|finer step sizes?|electropolish|ground and polished|etch(?:ed|ing)|sample preparation)\b', re.I)


class AcademicScorer:
    """
    G-Layer: Academic Generation & Quality Scoring.
    Provides logic for identifying, scoring, and aggregating high-value academic claims.
    Now integrated with AIAdapter for LLM-powered semantic understanding.
    """

    def __init__(self, goal: str, enable_llm: bool = True, api_key: Optional[str] = None, base_url: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.goal = goal
        self.ai_adapter = AIAdapter(api_key=api_key, base_url=base_url, model=model) if enable_llm else None
        self.use_llm = enable_llm and (self.ai_adapter and self.ai_adapter.enabled)

    @staticmethod
    def normalize_text(text: str) -> str:
        return re.sub(r'\s+', ' ', (text or '').replace('\xa0', ' ')).strip()

    @staticmethod
    def split_sentences(text: str) -> List[str]:
        text = AcademicScorer.normalize_text(text)
        if not text:
            return []
        parts = [p.strip() for p in SENT_SPLIT_RE.split(text) if p.strip()]
        return parts or [text]

    @staticmethod
    def en_tokens(text: str) -> List[str]:
        return [t.lower() for t in EN_TOKEN_RE.findall(text or '') if t.lower() not in STOPWORDS]

    @staticmethod
    def cn_tokens(text: str) -> List[str]:
        return [t for t in CN_TOKEN_RE.findall(text or '')]

    @staticmethod
    def token_set(text: str) -> Set[str]:
        return set(AcademicScorer.en_tokens(text) + [t.lower() for t in AcademicScorer.cn_tokens(text)])

    @staticmethod
    def jaccard(a: Set[str], b: Set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    @staticmethod
    def expand_goal(goal: str) -> Tuple[List[str], List[str], Counter]:
        goal = AcademicScorer.normalize_text(goal)
        phrase_terms: List[str] = []
        raw_terms = AcademicScorer.en_tokens(goal) + [t.lower() for t in AcademicScorer.cn_tokens(goal)]
        for cn, mapped in GOAL_MAP.items():
            if cn in goal:
                phrase_terms.extend(mapped)
                raw_terms.append(cn.lower())
        
        low = goal.lower()
        phrases = [
            'molten pool', 'heat input', 'welding direction', 'deep learning', 'transfer learning',
            'residual stress', 'grain morphology', 'constitutional supercooling', 'additive manufacturing',
            'columnar to equiaxed', 'grain refinement', 'strengthening mechanism', 'crack recognition'
        ]
        for phrase in phrases:
            if phrase in low:
                phrase_terms.append(phrase)
        
        weights = Counter(raw_terms)
        for p in phrase_terms:
            weights[p.lower()] += 2
        return raw_terms, sorted(set(phrase_terms)), weights

    @staticmethod
    def token_score(text: str, goal_terms: Counter, phrase_terms: List[str]) -> Tuple[float, List[str]]:
        low = text.lower()
        score = 0.0
        hits: List[str] = []
        tok_counts = Counter(AcademicScorer.en_tokens(text) + [t.lower() for t in AcademicScorer.cn_tokens(text)])
        for term, weight in goal_terms.items():
            if ' ' in term:
                if term in low:
                    score += 2.0 * weight
                    hits.append(term)
            else:
                if tok_counts.get(term, 0):
                    score += min(tok_counts[term], 3) * 0.9 * weight
                    hits.append(term)
        for phrase in phrase_terms:
            pl = phrase.lower()
            if pl in low and pl not in hits:
                score += 1.6
                hits.append(pl)
        return score, sorted(set(hits))

    @staticmethod
    def infer_goal_profile(goal: str) -> Dict[str, bool]:
        low = goal.lower()
        return {
            'method_focus': any(k in low for k in ['方法', 'method', 'simulation', '模型', 'model', 'image', '图像', 'dataset', 'experimental']),
            'image_focus': any(k in low for k in ['图像', 'image', 'deep learning', 'cnn', 'recognition']),
            'process_focus': any(k in low for k in ['熔池', '流动', 'transfer', 'transport', 'heat input']),
            'performance_focus': any(k in low for k in ['性能', 'hardness', 'wear', 'corrosion', 'accuracy']),
            'mechanism_focus': any(k in low for k in ['机制', 'mechanism', 'criterion', '判据', 'columnar']),
        }

    @staticmethod
    def classify_point_type(section_title: str, text: str, page: int, goal_profile: Dict[str, bool]) -> str:
        st = (section_title or '').lower()
        tx = text.lower()
        
        if 'abstract' in st:
            return 'result' if RESULT_CUES.search(tx) else 'summary'
        if 'introduction' in st or (page <= 2 and BACKGROUND_CUES.search(tx)):
            return 'background'
        if any(k in st for k in ['method', 'experimental', 'materials', 'procedure']):
            return 'method'
        if any(k in st for k in ['result', 'discussion', 'conclusion']):
            return 'mechanism' if (MECH_CUES.search(tx) and RESULT_CUES.search(tx)) else 'result'
        
        if MECH_CUES.search(tx): return 'mechanism'
        if RESULT_CUES.search(tx): return 'result'
        return 'discussion'

    @staticmethod
    def best_claim_selection(text: str, page: int, goal_terms: Counter, phrase_terms: List[str]) -> str:
        """Selects the single most representative academic sentence from a chunk."""
        sents = AcademicScorer.split_sentences(text)
        if not sents: return ""
        
        def score_sent(s: str) -> float:
            low = s.lower()
            goal_s, _ = AcademicScorer.token_score(s, goal_terms, phrase_terms)
            res_hit = 2.2 if RESULT_CUES.search(low) else 0.0
            mech_hit = 2.0 if MECH_CUES.search(low) else 0.0
            num_bonus = 0.45 * len(NUMERIC_RE.findall(s))
            score = goal_s * 0.22 + res_hit + mech_hit + num_bonus
            # Apply penalties for meta content
            if META_CUES.search(low): score -= 1.0
            return score

        ranked = sorted(sents, key=score_sent, reverse=True)
        return ranked[0][:400].strip() if ranked else ""

    def _enhance_claim_with_llm(self, claim: str, source_text: str, chunk_idx: int) -> Dict[str, Any]:
        """
        使用 LLM 增强 Claim 分析：添加机制提取、边界分类、创新点识别。
        """
        if not self.use_llm:
            return {
                'claim': claim,
                'mechanisms': [],
                'boundary_type': 'unknown',
                'boundary_confidence': 0.0,
                'innovation_points': [],
                'evidence_strength': 'unknown'
            }

        enhancements = {
            'claim': claim,
            'mechanisms': [],
            'boundary_type': 'unknown',
            'boundary_confidence': 0.0,
            'innovation_points': [],
            'evidence_strength': 'unknown'
        }

        try:
            # 1. 提取机制
            mechanisms = self.ai_adapter.extract_mechanisms(source_text, self.goal)
            enhancements['mechanisms'] = mechanisms[:2] if mechanisms else []
        except Exception as e:
            logging.getLogger(__name__).debug(f"机制提取失败: {e}")

        try:
            # 2. 边界分类
            boundary_result = self.ai_adapter.classify_claim_boundary(claim, source_text)
            enhancements['boundary_type'] = boundary_result.get('boundary_type', 'unknown')
            enhancements['boundary_confidence'] = boundary_result.get('confidence', 0.0)
        except Exception as e:
            logging.getLogger(__name__).debug(f"边界分类失败: {e}")

        try:
            # 3. 提取创新点（如果是结果类型的 claim）
            if 'result' in enhancements['boundary_type'] or 'explanation' in enhancements['boundary_type']:
                innovations = self.ai_adapter.extract_innovation_points(source_text, self.goal)
                enhancements['innovation_points'] = innovations[:1] if innovations else []
        except Exception as e:
            logging.getLogger(__name__).debug(f"创新点提取失败: {e}")

        return enhancements

    def _synthesize_themes(self, selected_points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        [v40.2] 将离散的论点聚类为学术主题，并生成合成摘要。
        """
        if not selected_points: return []
        
        # 简单聚类：基于 LLM 提取的 mechanism 标签进行分组
        from collections import defaultdict
        theme_map = defaultdict(list)
        for wp in selected_points:
            mechs = wp.get('llm_enhancements', {}).get('mechanisms', [])
            if mechs:
                primary_theme = mechs[0]
            else:
                primary_theme = wp.get('point_type', 'discussion')
            theme_map[primary_theme].append(wp)
            
        themes = []
        for theme_name, points in theme_map.items():
            # 为每个主题生成合成叙述
            combined_text = "\n".join([p['claim'] for p in points])
            summary = ""
            if self.use_llm:
                prompt = f"请根据以下关于'{theme_name}'的研究论点，合成一段连贯的学术综述（约150字）：\n{combined_text}"
                try:
                    summary = self.ai_adapter.complete(prompt)
                except:
                    summary = combined_text[:300] + "..."
            else:
                summary = combined_text[:300] + "..."
                
            themes.append({
                'theme_title': theme_name.capitalize(),
                'summary': summary,
                'writing_points': points,
                'linked_figure_ids': sorted({fid for p in points for fid in p.get('linked_figures', [])}),
                'linked_table_ids': sorted({tid for p in points for tid in p.get('linked_tables', [])})
            })
            
        return sorted(themes, key=lambda x: len(x['writing_points']), reverse=True)

    def _verify_multimodal_support(self, writing_point: Dict[str, Any], figures: List[Dict[str, Any]]) -> float:
        """
        多模态增强校验：利用 LLM 验证图表是否支撑该 Writing Point。
        返回增强的相关性分数。
        """
        if not self.use_llm or not writing_point.get('linked_figures'):
            return writing_point.get('relevance_score', 0.5)

        claim = writing_point.get('claim', '')
        fig_ids = writing_point.get('linked_figures', [])

        if not claim or not fig_ids:
            return writing_point.get('relevance_score', 0.5)

        try:
            base_score = writing_point.get('relevance_score', 0.5)
            support_scores = []

            for fig_id in fig_ids[:2]:  # 只检查前两个图
                fig = next((f for f in figures if f.get('figure_id') == fig_id), None)
                if not fig:
                    continue

                caption = fig.get('caption', '')
                support_score = self.ai_adapter.verify_multimodal_support(claim, caption)
                support_scores.append(support_score)

            if support_scores:
                avg_support = sum(support_scores) / len(support_scores)
                # 融合基础分数和多模态支撑分数
                return round(0.6 * base_score + 0.4 * avg_support, 4)

            return base_score
        except Exception as e:
            logging.getLogger(__name__).debug(f"多模态校验失败: {e}")
            return writing_point.get('relevance_score', 0.5)

    def analyze_bound_data(self, bound_data: Dict[str, Any], topk: int = 12) -> Dict[str, Any]:
        """
        Core analysis pipeline: scores and ranks all entities based on the goal.
        Now with LLM-powered semantic analysis and multimodal verification.
        """
        raw_terms, phrase_terms, goal_weights = self.expand_goal(self.goal)
        profile = self.infer_goal_profile(self.goal)

        raw_writing_points = []
        for idx, chunk in enumerate(bound_data.get('chunks', []), start=1):
            text = chunk.get('text', '')
            if len(text) < 40: continue

            claim = self.best_claim_selection(text, chunk.get('page', 0), goal_weights, phrase_terms)
            p_type = self.classify_point_type(chunk.get('section_title', ''), claim, chunk.get('page', 0), profile)

            # Baseline relevance scoring
            g_score, hits = self.token_score(claim, goal_weights, phrase_terms)
            relevance = round(1.0 / (1.0 + math.exp(-(g_score - 2.0) * 0.5)), 4)

            writing_point = {
                'writing_point_id': f"wp{idx:03d}",
                'claim': claim,
                'point_type': p_type,
                'relevance_score': relevance,
                'goal_hits': hits,
                'page': chunk.get('page'),
                'source_text': text,
                'linked_figures': [e['target_id'] for e in bound_data.get('relation_edges', []) if e['source_id'] == chunk['chunk_id'] and e['target_type'] == 'figure'],
                'linked_tables': [e['target_id'] for e in bound_data.get('relation_edges', []) if e['source_id'] == chunk['chunk_id'] and e['target_type'] == 'table'],
            }

            # LLM 增强分析
            if self.use_llm:
                enhancements = self._enhance_claim_with_llm(claim, text, idx)
                writing_point['llm_enhancements'] = enhancements
                # 使用边界分类信息重新分类 point_type
                if enhancements.get('boundary_type') != 'unknown':
                    boundary_to_type = {
                        'result_fact': 'result',
                        'explanation': 'mechanism',
                        'inference': 'discussion',
                        'review_statement': 'background'
                    }
                    writing_point['point_type'] = boundary_to_type.get(enhancements['boundary_type'], p_type)

            raw_writing_points.append(writing_point)

        # 2. Ranking and Selection
        sorted_points = sorted(raw_writing_points, key=lambda x: x['relevance_score'], reverse=True)
        selected_points = sorted_points[:topk]

        # 3. Multimodal 增强验证 (如果启用 LLM)
        figures = bound_data.get('figures', []) or []
        if self.use_llm:
            for wp in selected_points:
                enhanced_score = self._verify_multimodal_support(wp, figures)
                wp['relevance_score'] = enhanced_score

        selected_figure_ids = {fid for wp in selected_points for fid in wp.get('linked_figures', [])}
        selected_table_ids = {tid for wp in selected_points for tid in wp.get('linked_tables', [])}

        tables = bound_data.get('tables', []) or []

        selected_figures = [
            {
                'figure_id': fig.get('figure_id'),
                'figure_number': fig.get('figure_number'),
                'page': fig.get('page'),
                'caption': fig.get('caption', ''),
                'bbox': fig.get('bbox'),
                'relevance_score': 0.5,
            }
            for fig in figures
            if fig.get('figure_id') in selected_figure_ids
        ]
        selected_tables = [
            {
                'table_id': tab.get('table_id'),
                'table_number': tab.get('table_number'),
                'page': tab.get('page'),
                'caption': tab.get('caption', ''),
                'relevance_score': 0.5,
            }
            for tab in tables
            if tab.get('table_id') in selected_table_ids
        ]

        # 4. 主题化合成 [NEW v40.2]
        semantic_themes = self._synthesize_themes(selected_points)

        return {
            'goal': self.goal,
            'goal_profile': profile,
            'writing_points': sorted_points,
            'selected_writing_points': selected_points,
            'semantic_themes': semantic_themes,
            'selected_figures': selected_figures,
            'selected_tables': selected_tables,
            'selected_references': [],
            'selected_parameters': [],
            'selected_results': [],
            'stats_analysis': {
                'writing_point_count': len(sorted_points),
                'selected_writing_point_count': len(selected_points),
                'selected_figure_count': len(selected_figures),
                'selected_table_count': len(selected_tables),
            },
            'status': 'analysis_complete'
        }
