from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

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


def normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').replace('\xa0', ' ')).strip()


def split_sentences(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    parts = [p.strip() for p in SENT_SPLIT_RE.split(text) if p.strip()]
    return parts or [text]


def en_tokens(text: str) -> list[str]:
    return [t.lower() for t in EN_TOKEN_RE.findall(text or '') if t.lower() not in STOPWORDS]


def cn_tokens(text: str) -> list[str]:
    return [t for t in CN_TOKEN_RE.findall(text or '')]


def token_set(text: str) -> set[str]:
    return set(en_tokens(text) + [t.lower() for t in cn_tokens(text)])


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def expand_goal(goal: str) -> tuple[list[str], list[str], Counter]:
    goal = normalize_text(goal)
    phrase_terms: list[str] = []
    raw_terms = en_tokens(goal) + [t.lower() for t in cn_tokens(goal)]
    for cn, mapped in GOAL_MAP.items():
        if cn in goal:
            phrase_terms.extend(mapped)
            raw_terms.append(cn.lower())
    low = goal.lower()
    for phrase in [
        'molten pool', 'heat input', 'welding direction', 'deep learning', 'transfer learning',
        'residual stress', 'grain morphology', 'constitutional supercooling', 'additive manufacturing',
        'columnar to equiaxed', 'grain refinement', 'strengthening mechanism', 'crack recognition'
    ]:
        if phrase in low:
            phrase_terms.append(phrase)
    weights = Counter(raw_terms)
    for p in phrase_terms:
        weights[p.lower()] += 2
    return raw_terms, sorted(set(phrase_terms)), weights


def token_score(text: str, goal_terms: Counter, phrase_terms: list[str]) -> tuple[float, list[str]]:
    low = text.lower()
    score = 0.0
    hits: list[str] = []
    tok_counts = Counter(en_tokens(text) + [t.lower() for t in cn_tokens(text)])
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


def infer_goal_profile(goal: str) -> dict[str, bool]:
    low = goal.lower()
    method_focus = any(k in low for k in ['方法', 'method', 'simulation', '模型', 'model', 'image', '图像', 'dataset', 'experimental'])
    image_focus = any(k in low for k in ['图像', 'image', 'deep learning', 'cnn', 'recognition', '裂纹'])
    process_focus = any(k in low for k in ['熔池', '流动', 'transfer', 'transport', 'nitrid', 'heat input', 'welding direction'])
    performance_focus = any(k in low for k in ['性能', 'hardness', 'wear', 'corrosion', 'accuracy', 'tensile'])
    mechanism_focus = any(k in low for k in ['机制', 'mechanism', 'criterion', '判据', 'columnar', 'equiaxed', 'strengthening'])
    return {
        'method_focus': method_focus,
        'image_focus': image_focus,
        'process_focus': process_focus,
        'performance_focus': performance_focus,
        'mechanism_focus': mechanism_focus,
    }


def looks_like_front_matter(text: str, section_title: str | None, page: int) -> bool:
    tx = normalize_text(text)
    low = tx.lower()
    st = (section_title or '').lower()
    if not tx:
        return True
    if len(tx) < 30:
        return True
    if page <= 2 and (AFFILIATION_CUES.search(low) or TITLE_AUTHORISH_CUES.search(low)):
        if not RESULT_CUES.search(low) and not MECH_CUES.search(low):
            return True
    if page == 1 and tx.count(',') >= 4 and not re.search(r'[\.!?。；;]', tx):
        return True
    if page == 1 and any(k in low for k in ['journal homepage', 'available online', 'corresponding author', 'state key laboratory']):
        return True
    if st and (AFFILIATION_CUES.search(st) or TITLE_AUTHORISH_CUES.search(st)) and page <= 2 and not RESULT_CUES.search(low):
        return True
    return False


def classify_point_type(section_title: str, text: str, page: int, goal_profile: dict[str, bool]) -> str:
    st = (section_title or '').lower()
    tx = text.lower()
    if looks_like_front_matter(text, section_title, page):
        return 'meta'
    if 'abstract' in st:
        if RESULT_CUES.search(tx):
            return 'result'
        return 'summary'
    if 'introduction' in st or (page <= 2 and BACKGROUND_CUES.search(tx) and len(NUMERIC_RE.findall(tx)) <= 1):
        return 'background'
    if any(k in st for k in ['method', 'experimental', 'materials', 'procedure']):
        return 'method'
    if re.search(r'\b(recent studies|previous studies|et al|introduced|reported)\b', tx) and not re.search(r'\b(this study|our|herein|in this work|present work)\b', tx):
        if page <= 3:
            return 'background'
    if any(k in st for k in ['result', 'discussion', 'conclusion']):
        if MECH_CUES.search(tx) and RESULT_CUES.search(tx):
            return 'mechanism'
        if RESULT_CUES.search(tx):
            return 'result'
    if HARDWARE_CUES.search(tx):
        return 'method'
    if METHOD_LISTING_CUES.search(tx):
        return 'method'
    if METHOD_CUES.search(tx) and not RESULT_CUES.search(tx) and not MECH_CUES.search(tx):
        return 'method'
    if MODEL_REFERENCE_CUES.search(tx) and not CURRENT_WORK_CUES.search(tx):
        return 'background' if page <= 3 else 'discussion'
    if DEFINITION_HEAVY_CUES.search(tx) and not CURRENT_WORK_CUES.search(tx):
        return 'discussion'
    if MECH_CUES.search(tx):
        return 'mechanism'
    if BACKGROUND_CUES.search(tx):
        return 'background'
    if RESULT_CUES.search(tx) or (len(NUMERIC_RE.findall(tx)) >= 2 and goal_profile['performance_focus']):
        return 'result'
    return 'discussion'


def classify_boundary(text: str, point_type: str = '') -> str:
    low = text.lower()
    has_num = bool(NUMERIC_RE.search(low))
    has_mech = bool(MECH_CUES.search(low))
    has_hedge = bool(HEDGE_CUES.search(low))
    has_result = bool(RESULT_CUES.search(low))
    if point_type == 'background':
        return 'background_reference'
    if has_mech and not has_hedge:
        return 'explanation'
    if has_result and has_num and not has_hedge:
        return 'result'
    if has_hedge:
        return 'inference'
    return 'unclear'


def boundary_note(boundary: str) -> str:
    notes = {
        'result': '作者直接报告的结果，可直接作为结果事实使用。',
        'explanation': '作者给出的解释或机理说明，可用于解释层，不宜改写成独立事实。',
        'inference': '带推测色彩，只宜保守转述。',
        'background_reference': '背景或前人工作转述，使用时应保留原始参考文献编号。',
        'unclear': '证据边界不够清晰，使用时需回查原文。',
    }
    return notes.get(boundary, '证据边界未明确，使用时需回查原文。')


def sentence_meta_penalty(sent: str) -> float:
    low = sent.lower()
    penalty = 0.0
    if META_CUES.search(low) and not RESULT_CUES.search(low) and not MECH_CUES.search(low):
        penalty += 1.4
    if HARDWARE_CUES.search(low):
        penalty += 1.8
    if re.search(r'\b(samples? were produced|was used to|were used to|models? .* (given|listed)|shown in fig|listed in table)\b', low):
        penalty += 1.2
    if METHOD_LISTING_CUES.search(low):
        penalty += 1.6
    if low.count('fig.') + low.count('figure') + low.count('table') >= 2 and len(NUMERIC_RE.findall(low)) <= 1:
        penalty += 1.0
    if re.search(r'\b(doi|copyright|creativecommons|journal|supplementary|author contribution)\b', low):
        penalty += 2.0
    if FORMULA_EXPOSITION_CUES.search(low) and not RESULT_CUES.search(low) and not COMPARISON_CUE_RE.search(low):
        penalty += 1.8
    if VISUAL_DESCRIPTION_CUES.search(low) and not COMPARISON_CUE_RE.search(low) and not MECH_CUES.search(low):
        penalty += 0.9
    if CAPTIONISH_CUES.search(low) and not COMPARISON_CUE_RE.search(low) and not RESULT_CUES.search(low):
        penalty += 1.0
    if PANEL_PREFIX_CUES.search((sent or '').strip()) and len(NUMERIC_RE.findall(low)) < 2:
        penalty += 0.8
    if LEGENDISH_CUES.search(low):
        penalty += 1.2
    if MODEL_REFERENCE_CUES.search(low) and not CURRENT_WORK_CUES.search(low):
        penalty += 1.6
    if DEFINITION_HEAVY_CUES.search(low) and not CURRENT_WORK_CUES.search(low):
        penalty += 1.6
    return penalty


def best_claim(text: str, section_title: str, page: int, goal_terms: Counter, phrase_terms: list[str], goal_profile: dict[str, bool]) -> str:
    sents = split_sentences(text)
    if not sents:
        return ''
    def score_sent(s: str) -> tuple[float, int, int, int]:
        low = s.lower()
        goal_raw, _ = token_score(s, goal_terms, phrase_terms)
        result_hit = 1 if RESULT_CUES.search(low) else 0
        mech_hit = 1 if MECH_CUES.search(low) else 0
        nums = len(NUMERIC_RE.findall(s))
        cmp_hit = 1 if COMPARISON_CUE_RE.search(low) else 0
        perf_hit = 1 if re.search(r'\b(hardness|wear|corrosion|accuracy|tensile|strength|loss)\b', low) else 0
        method_pen = 1 if (METHOD_CUES.search(low) and not result_hit and not mech_hit and not goal_profile['method_focus']) else 0
        meta_pen = sentence_meta_penalty(s)
        early_pen = 0.8 if page <= 2 and BACKGROUND_CUES.search(low) and not result_hit and not mech_hit else 0.0
        literature_pen = 1.4 if (LITERATURE_CUES.search(low) and not CURRENT_WORK_CUES.search(low) and not result_hit and not mech_hit) else 0.0
        proxy_pen = 1.2 if (PROXY_BACKGROUND_CUES.search(low) and not result_hit and not mech_hit) else 0.0
        generic_pen = 1.0 if (GENERIC_STATEMENT_CUES.search(low) and not CURRENT_WORK_CUES.search(low)) else 0.0
        current_bonus = 0.9 if CURRENT_WORK_CUES.search(low) else 0.0
        direct_bonus = 0.8 if (('fig.' in low or 'figure' in low or 'table' in low) and (result_hit or mech_hit or nums >= 2)) else 0.0
        formula_pen = 1.5 if (FORMULA_EXPOSITION_CUES.search(low) and not result_hit and not cmp_hit and not mech_hit) else 0.0
        visual_pen = 1.0 if (VISUAL_DESCRIPTION_CUES.search(low) and not cmp_hit and not mech_hit and nums < 2) else 0.0
        captionish_pen = 1.2 if (CAPTIONISH_CUES.search(low) and not cmp_hit and not mech_hit and nums < 2) else 0.0
        panel_pen = 0.9 if (PANEL_PREFIX_CUES.search(s.strip()) and nums < 2 and not cmp_hit) else 0.0
        legend_pen = 1.4 if (LEGENDISH_CUES.search(low) and not cmp_hit and nums < 3) else 0.0
        model_pen = 1.8 if (MODEL_REFERENCE_CUES.search(low) and not CURRENT_WORK_CUES.search(low)) else 0.0
        definition_pen = 1.8 if (DEFINITION_HEAVY_CUES.search(low) and not CURRENT_WORK_CUES.search(low)) else 0.0
        external_pen = 2.0 if (re.search(r'\bet al\.?\b|\bas shown by\b', low) and not CURRENT_WORK_CUES.search(low)) else 0.0
        citation_lead_pen = 2.0 if (re.match(r'^\s*\[?\d+\]?\s*(indicates?|shows?|reported|suggested)', low) and not CURRENT_WORK_CUES.search(low)) else 0.0
        method_list_pen = 1.8 if (METHOD_LISTING_CUES.search(low) and not goal_profile['method_focus']) else 0.0
        score = 2.2*result_hit + 2.0*mech_hit + 0.45*nums + 1.1*cmp_hit + 0.8*perf_hit + 0.22*min(goal_raw, 10) + current_bonus + direct_bonus - 1.0*method_pen - meta_pen - early_pen - literature_pen - proxy_pen - generic_pen - formula_pen - visual_pen - captionish_pen - panel_pen - legend_pen - model_pen - definition_pen - external_pen - citation_lead_pen - method_list_pen
        return score, result_hit, mech_hit, nums
    ranked = sorted(sents, key=score_sent, reverse=True)
    return ranked[0][:420].strip()


def extract_support_maps(edges: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]], dict[str, list[str]]]:
    chunk_to_figs: dict[str, set[str]] = defaultdict(set)
    chunk_to_tabs: dict[str, set[str]] = defaultdict(set)
    chunk_to_refs: dict[str, set[str]] = defaultdict(set)
    chunk_rel_types: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.get('source_type') != 'chunk':
            continue
        sid = e.get('source_id')
        chunk_rel_types[sid].append(e.get('relation_type', ''))
        if e.get('target_type') == 'figure':
            chunk_to_figs[sid].add(e.get('target_id'))
        elif e.get('target_type') == 'table':
            chunk_to_tabs[sid].add(e.get('target_id'))
        elif e.get('target_type') == 'reference':
            chunk_to_refs[sid].add(e.get('target_id'))
    return chunk_to_figs, chunk_to_tabs, chunk_to_refs, chunk_rel_types


def build_lookup(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(it[key]): it for it in items if key in it}


def score_evidence(figs: list[str], tabs: list[str], refs: list[str], param_n: int, result_n: int, relation_types: list[str]) -> float:
    rel_boost = 0.12 if any(rt in {'explicit_mention', 'caption_nearby_semantic'} for rt in relation_types) else 0.0
    val = 0.30*len(figs) + 0.22*len(tabs) + 0.05*min(len(refs), 4) + 0.12*param_n + 0.22*result_n + rel_boost
    return round(min(1.0, val), 4)


def build_causal_chain(claim: str, point_type: str) -> list[str]:
    low = claim.lower()
    chain: list[str] = []
    if any(k in low for k in ['power', 'speed', 'frequency', 'heat input', 'current', 'voltage', 'ratio', 'composition', 'parameter']):
        chain.append('parameter')
    if any(k in low for k in ['molten pool', 'flow', 'convection', 'cooling rate', 'transport', 'transfer', 'nitriding', 'weld pool']):
        chain.append('process')
    if any(k in low for k in ['grain', 'microstructure', 'phase', 'texture', 'precipitate', 'equiaxed', 'columnar', 'γ', 'carbide', 'dendrite']):
        chain.append('microstructure')
    if any(k in low for k in ['stress', 'residual', 'tensile', 'compressive']):
        chain.append('stress')
    if any(k in low for k in ['hardness', 'wear', 'corrosion', 'accuracy', 'performance', 'tensile', 'friction', 'strength', 'loss']):
        chain.append('performance')
    if not chain:
        chain = [point_type if point_type in {'method', 'background'} else 'observation']
    return chain


def classify_citation_role(point_type: str, claim: str, linked_refs: list[str], linked_figs: list[str], linked_tabs: list[str], linked_results: list[str]) -> str:
    low = claim.lower()
    if not linked_refs:
        return 'none'
    current_work_like = bool(re.search(r'\b(this study|our|herein|in this work|present work)\b', low, re.I)) or bool(linked_figs or linked_tabs or linked_results)
    literature_like = bool(re.search(r'\b(et al|previous studies|reported|review|recent studies|introduced)\b', low, re.I))
    if point_type == 'background' or (literature_like and not current_work_like):
        return 'background_reference'
    if current_work_like and not literature_like:
        return 'current_work_reference'
    return 'mixed_reference'


def goal_alignment_note(goal_hits: list[str], causal_roles: list[str], point_type: str) -> str:
    parts = []
    if goal_hits:
        parts.append('命中目标词: ' + ', '.join(goal_hits[:6]))
    if causal_roles:
        parts.append('因果角色: ' + ' → '.join(causal_roles[:4]))
    parts.append('类型: ' + point_type)
    return '；'.join(parts)


def current_work_signal(claim: str, page: int, section_title: str | None, linked_figs: list[str], linked_tabs: list[str], linked_results: list[str], linked_refs: list[str]) -> float:
    low = (claim or '').lower()
    st = (section_title or '').lower()
    score = 0.0
    if CURRENT_WORK_CUES.search(low):
        score += 0.42
    if linked_results:
        score += 0.28
    if linked_figs or linked_tabs:
        score += 0.18
    if page >= 3:
        score += 0.08
    if RESULT_SECTION_CUES.search(st):
        score += 0.12
    if LITERATURE_CUES.search(low) and not (linked_figs or linked_tabs or linked_results):
        score -= 0.24
    if re.search(r'\b(et al\.?|introduced|reported|recent studies|ImageNet|ILSVRC)\b', low) and len(linked_refs) >= 1:
        score -= 0.18
    if MODEL_REFERENCE_CUES.search(low) and not CURRENT_WORK_CUES.search(low):
        score -= 0.18
    if DEFINITION_HEAVY_CUES.search(low) and not CURRENT_WORK_CUES.search(low):
        score -= 0.18
    return max(0.0, min(1.0, score))


def background_burden(claim: str, page: int, linked_figs: list[str], linked_tabs: list[str], linked_results: list[str], linked_refs: list[str]) -> float:
    low = (claim or '').lower()
    burden = 0.0
    if LITERATURE_CUES.search(low):
        burden += 0.34
    if PROXY_BACKGROUND_CUES.search(low):
        burden += 0.22
    if page <= 3:
        burden += 0.10
    if len(linked_refs) >= 2 and not (linked_figs or linked_tabs or linked_results):
        burden += 0.22
    if re.search(r'\b(in 20\d{2}|challenge|review|widely used)\b', low):
        burden += 0.16
    if MODEL_REFERENCE_CUES.search(low) and not CURRENT_WORK_CUES.search(low):
        burden += 0.22
    if DEFINITION_HEAVY_CUES.search(low) and not CURRENT_WORK_CUES.search(low):
        burden += 0.22
    return max(0.0, min(1.0, burden))


def choose_top_points(writing_points: list[dict[str, Any]], topk: int, goal_profile: dict[str, bool]) -> list[dict[str, Any]]:
    def sort_key(x: dict[str, Any]) -> tuple[float, float, float, float]:
        return (x['relevance_score'], x.get('current_work_score', 0.0), x['evidence_strength'], x['analysis_confidence'])

    sorted_points = sorted(writing_points, key=sort_key, reverse=True)
    selected: list[dict[str, Any]] = []
    type_counts = Counter()
    page_counts = Counter()
    selected_ids: set[str] = set()

    def accept(pt: dict[str, Any], strict: bool) -> bool:
        ptype = pt['point_type']
        if ptype == 'meta':
            return False
        if strict:
            if ptype not in {'result', 'mechanism'}:
                return False
            claim = pt.get('claim', '')
            if LITERATURE_CUES.search(claim) and not CURRENT_WORK_CUES.search(claim):
                return False
            if PROXY_BACKGROUND_CUES.search(claim) and not CURRENT_WORK_CUES.search(claim):
                return False
            if GENERIC_STATEMENT_CUES.search(claim) and not CURRENT_WORK_CUES.search(claim):
                return False
            if FORMULA_EXPOSITION_CUES.search(claim) and not COMPARISON_CUE_RE.search(claim):
                return False
            if VISUAL_DESCRIPTION_CUES.search(claim) and not (COMPARISON_CUE_RE.search(claim) or RESULT_CUES.search(claim) or MECH_CUES.search(claim)):
                return False
            if CAPTIONISH_CUES.search(claim) and not (COMPARISON_CUE_RE.search(claim) or MECH_CUES.search(claim)):
                return False
            if PANEL_PREFIX_CUES.search(claim.strip()) and len(NUMERIC_RE.findall(claim)) < 2 and not COMPARISON_CUE_RE.search(claim):
                return False
            if pt.get('background_burden', 0.0) >= 0.35 and pt.get('current_work_score', 0.0) < 0.50:
                return False
            if pt.get('citation_role') == 'background_reference':
                return False
            if pt.get('boundary_type') in {'background_reference'}:
                return False
            if re.search(r'\bet al\.?\b|\bas shown by\b', claim, re.I) and not CURRENT_WORK_CUES.search(claim):
                return False
            if re.search(r'present[s]? the overall morpholog', claim, re.I):
                return False
            if LEGENDISH_CUES.search(claim):
                return False
            if MODEL_REFERENCE_CUES.search(claim) and not CURRENT_WORK_CUES.search(claim):
                return False
            if DEFINITION_HEAVY_CUES.search(claim) and not CURRENT_WORK_CUES.search(claim):
                return False
            if METHOD_LISTING_CUES.search(claim) and not goal_profile.get('method_focus'):
                return False
            if re.match(r'^\s*\[?\d+\]?\s*(indicates?|shows?|reported|suggested)', claim, re.I) and not CURRENT_WORK_CUES.search(claim):
                return False
            if pt.get('current_work_score', 0.0) < 0.22 and pt.get('linked_results') == [] and pt.get('linked_figures') == [] and pt.get('linked_tables') == []:
                return False
        else:
            if ptype == 'background' and not goal_profile.get('method_focus'):
                return False
            if FORMULA_EXPOSITION_CUES.search(pt.get('claim','')) and not COMPARISON_CUE_RE.search(pt.get('claim','')):
                return False
            if CAPTIONISH_CUES.search(pt.get('claim','')) and not COMPARISON_CUE_RE.search(pt.get('claim','')):
                return False
            if re.search(r'\bet al\.?\b|\bas shown by\b', pt.get('claim',''), re.I) and not CURRENT_WORK_CUES.search(pt.get('claim','')):
                return False
            if re.search(r'present[s]? the overall morpholog', pt.get('claim',''), re.I):
                return False
            if LEGENDISH_CUES.search(pt.get('claim','')):
                return False
            if MODEL_REFERENCE_CUES.search(pt.get('claim','')) and not CURRENT_WORK_CUES.search(pt.get('claim','')):
                return False
            if DEFINITION_HEAVY_CUES.search(pt.get('claim','')) and not CURRENT_WORK_CUES.search(pt.get('claim','')):
                return False
            if METHOD_LISTING_CUES.search(pt.get('claim','')) and not goal_profile.get('method_focus'):
                return False
            if re.match(r'^\s*\[?\d+\]?\s*(indicates?|shows?|reported|suggested)', pt.get('claim',''), re.I) and not CURRENT_WORK_CUES.search(pt.get('claim','')):
                return False
            if pt.get('background_burden', 0.0) >= 0.52 and pt.get('current_work_score', 0.0) < 0.38:
                return False
        if page_counts[pt.get('page', 0)] >= 3 and ptype not in {'result', 'mechanism'}:
            return False
        return True

    for strict in (True, False):
        for pt in sorted_points:
            if len(selected) >= topk:
                break
            if pt['writing_point_id'] in selected_ids:
                continue
            if not accept(pt, strict):
                continue
            ptype = pt['point_type']
            if strict and type_counts[ptype] >= topk:
                continue
            selected.append(pt)
            selected_ids.add(pt['writing_point_id'])
            type_counts[ptype] += 1
            page_counts[pt.get('page', 0)] += 1

    return selected[:topk]


def point_signature_tokens(claim: str, goal_hits: list[str]) -> set[str]:
    tokens = token_set(claim)
    if goal_hits:
        tokens.update(h.lower() for h in goal_hits[:6])
    return {t for t in tokens if len(t) > 1}


def aggregate_writing_points(raw_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(raw_points, key=lambda x: (x['relevance_score'], x['evidence_strength'], x['analysis_confidence']), reverse=True)
    groups: list[dict[str, Any]] = []
    for wp in ordered:
        claim_tokens = point_signature_tokens(wp['claim'], wp['goal_hits'])
        evidence = set(wp['linked_figures']) | set(wp['linked_tables']) | set(wp['linked_results'])
        matched = None
        best_match = 0.0
        for grp in groups:
            same_family = (wp['point_type'] == grp['point_type']) or ({wp['point_type'], grp['point_type']} <= {'result', 'mechanism', 'discussion'})
            if not same_family:
                continue
            tok_sim = jaccard(claim_tokens, grp['claim_tokens'])
            evidence_overlap = 0.0
            if evidence and grp['evidence_union']:
                evidence_overlap = len(evidence & grp['evidence_union']) / max(len(evidence | grp['evidence_union']), 1)
            page_gap = abs(int(wp.get('page') or 0) - int(grp.get('page') or 0))
            match_score = max(tok_sim, 0.7 * tok_sim + 0.6 * evidence_overlap)
            if tok_sim >= 0.55 or (tok_sim >= 0.32 and evidence_overlap >= 0.18) or (evidence_overlap >= 0.55 and page_gap <= 2):
                if match_score > best_match:
                    best_match = match_score
                    matched = grp
        if matched is None:
            groups.append({
                'claim_tokens': set(claim_tokens),
                'evidence_union': set(evidence),
                'raw_items': [wp],
                'best_item': wp,
                'point_type': wp['point_type'],
                'page': wp.get('page', 0),
                'goal_hits': set(wp['goal_hits']),
            })
        else:
            matched['raw_items'].append(wp)
            matched['claim_tokens'].update(claim_tokens)
            matched['evidence_union'].update(evidence)
            matched['goal_hits'].update(wp['goal_hits'])
            current_best_key = (matched['best_item']['relevance_score'], matched['best_item'].get('current_work_score', 0.0), matched['best_item']['evidence_strength'])
            new_key = (wp['relevance_score'], wp.get('current_work_score', 0.0), wp['evidence_strength'])
            if new_key > current_best_key:
                matched['best_item'] = wp
                matched['page'] = wp.get('page', 0)

    aggregated: list[dict[str, Any]] = []
    for idx, grp in enumerate(groups, start=1):
        items = grp['raw_items']
        best = grp['best_item']
        linked_figures = sorted({fid for it in items for fid in it['linked_figures']})
        linked_tables = sorted({tid for it in items for tid in it['linked_tables']})
        linked_references = sorted({rid for it in items for rid in it['linked_references']})
        linked_parameters = sorted({pid for it in items for pid in it['linked_parameters']})
        linked_results = sorted({rid for it in items for rid in it['linked_results']})
        raw_ids = [it['raw_writing_point_id'] for it in items]
        support_chunks = sorted({it['source_chunk_id'] for it in items})
        support_pages = sorted({int(it.get('page') or 0) for it in items})
        support_strength = min(1.0, best['evidence_strength'] + 0.03 * max(0, len(items) - 1))
        relevance_score = min(1.0, max(it['relevance_score'] for it in items) + 0.025 * max(0, len(items) - 1))
        confidence = min(1.0, max(it['analysis_confidence'] for it in items) + 0.02 * max(0, len(items) - 1))
        current_work_score = max(it.get('current_work_score', 0.0) for it in items)
        background_load = min(1.0, sum(it.get('background_burden', 0.0) for it in items) / max(len(items), 1))
        boundary_votes = Counter(it['boundary_type'] for it in items)
        boundary = boundary_votes.most_common(1)[0][0]
        point_type_votes = Counter(it['point_type'] for it in items)
        point_type = point_type_votes.most_common(1)[0][0]
        citation_role = classify_citation_role(point_type, best['claim'], linked_references, linked_figures, linked_tables, linked_results)
        evidence_bundle_ids = [f'figure::{fid}' for fid in linked_figures] + [f'table::{tid}' for tid in linked_tables]
        selection_reason = (
            f"由 {len(items)} 个相近原始写作点聚合；"
            f"证据包含 {len(linked_figures)} 图 / {len(linked_tables)} 表 / {len(linked_results)} 结果 / {len(linked_parameters)} 参数；"
            f"相关度 {relevance_score:.2f}。"
        )
        aggregated.append({
            'writing_point_id': f'wp{idx:04d}',
            'raw_writing_point_ids': raw_ids,
            'source_chunk_ids': support_chunks,
            'page': best.get('page'),
            'pages': support_pages,
            'section_id': best.get('section_id'),
            'section_title': best.get('section_title'),
            'point_type': point_type,
            'boundary_type': boundary,
            'boundary_note': boundary_note(boundary),
            'citation_role': citation_role,
            'claim': best['claim'],
            'representative_claim': best['claim'],
            'source_text': best['source_text'],
            'causal_roles': sorted({role for it in items for role in it['causal_roles']}),
            'goal_hits': sorted(grp['goal_hits']),
            'goal_alignment_note': goal_alignment_note(sorted(grp['goal_hits']), sorted({role for it in items for role in it['causal_roles']}), point_type),
            'relevance_score': round(relevance_score, 4),
            'evidence_strength': round(support_strength, 4),
            'analysis_confidence': round(confidence, 4),
            'current_work_score': round(current_work_score, 4),
            'background_burden': round(background_load, 4),
            'linked_figures': linked_figures,
            'linked_tables': linked_tables,
            'linked_references': linked_references,
            'linked_parameters': linked_parameters,
            'linked_results': linked_results,
            'relation_types': sorted({rt for it in items for rt in it['relation_types']}),
            'support_count': len(items),
            'selection_reason': selection_reason,
            'evidence_bundle_ids': evidence_bundle_ids,
        })
    aggregated.sort(key=lambda x: (x['relevance_score'], x.get('current_work_score', 0.0), -x.get('background_burden', 0.0), x['evidence_strength'], x['analysis_confidence']), reverse=True)
    return aggregated


def build_cluster_boost(evidence_clusters: list[dict[str, Any]]) -> dict[str, float]:
    cluster_boost: dict[str, float] = defaultdict(float)
    for cl in evidence_clusters or []:
        try:
            support_strength = float(cl.get('support_strength', 0.0) or 0.0)
        except Exception:
            support_strength = 0.0
        anchor_type = cl.get('anchor_type')
        anchor_id = cl.get('anchor_id')
        if anchor_type and anchor_id:
            cluster_boost[f'{anchor_type}::{anchor_id}'] = max(cluster_boost[f'{anchor_type}::{anchor_id}'], support_strength)
    return cluster_boost


def score_ranked_cards(cards: list[dict[str, Any]], support_points: list[dict[str, Any]], goal_terms: Counter, goal_phrase_terms: list[str], card_type: str) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for card in cards:
        key = f'{card_type}_id'
        cid = card.get(key)
        supporting = [wp for wp in support_points if cid in wp.get(f'linked_{card_type}s', [])]
        best_wp = max((wp['relevance_score'] for wp in supporting), default=0.0)
        avg_wp = (sum(wp['relevance_score'] for wp in supporting) / len(supporting)) if supporting else 0.0
        text = card.get('text', '') or card.get('caption', '')
        cap_score, cap_hits = token_score(text, goal_terms, goal_phrase_terms)
        numeric_bonus = min(0.12, 0.03 * len(NUMERIC_RE.findall(text)))
        param_bonus = 0.08 if PARAMETER_TERM_RE.search(text) else 0.0
        res_bonus = 0.10 if RESULT_CUES.search(text) else 0.0
        score = min(1.0, 0.52*best_wp + 0.18*avg_wp + 0.12*min(cap_score/8.0, 1.0) + numeric_bonus + param_bonus + res_bonus)
        ranked.append({
            key: cid,
            'chunk_id': card.get('chunk_id'),
            'page': card.get('page'),
            'text': text,
            'relevance_score': round(score, 4),
            'goal_hits': cap_hits,
            'supporting_writing_point_ids': [wp['writing_point_id'] for wp in supporting[:12]],
            'selection_reason': f'由 {len(supporting)} 个写作点支撑，且与目标词 {", ".join(cap_hits[:5]) if cap_hits else "弱命中"} 对齐。',
        })
    ranked.sort(key=lambda x: x['relevance_score'], reverse=True)
    return ranked


def analyze_bound(bound: dict[str, Any], goal: str, topk: int = 12) -> dict[str, Any]:
    chunks = bound.get('chunks', [])
    figures = bound.get('figures', [])
    tables = bound.get('tables', [])
    references = bound.get('references', [])
    parameter_cards = bound.get('parameter_cards', [])
    result_cards = bound.get('result_cards', [])
    edges = bound.get('relation_edges', [])
    evidence_clusters = bound.get('evidence_clusters', [])

    _, goal_phrase_terms, goal_terms = expand_goal(goal)
    goal_profile = infer_goal_profile(goal)
    chunk_to_figs, chunk_to_tabs, chunk_to_refs, chunk_rel_types = extract_support_maps(edges)

    params_by_chunk: dict[str, list[str]] = defaultdict(list)
    for p in parameter_cards:
        params_by_chunk[p['chunk_id']].append(p['parameter_id'])
    results_by_chunk: dict[str, list[str]] = defaultdict(list)
    for r in result_cards:
        results_by_chunk[r['chunk_id']].append(r['result_id'])

    fig_lookup = build_lookup(figures, 'figure_id')
    tab_lookup = build_lookup(tables, 'table_id')

    raw_writing_points: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        text = normalize_text(chunk.get('text', ''))
        page = int(chunk.get('page') or 0)
        if looks_like_front_matter(text, chunk.get('section_title'), page):
            continue
        if len(text) < 40:
            continue
        claim = best_claim(text, chunk.get('section_title', ''), page, goal_terms, goal_phrase_terms, goal_profile)
        point_type = classify_point_type(chunk.get('section_title', ''), claim or text, page, goal_profile)
        if point_type == 'meta':
            continue
        boundary = classify_boundary(claim or text, point_type)
        linked_figs = sorted(chunk_to_figs.get(chunk['chunk_id'], set()))
        linked_tabs = sorted(chunk_to_tabs.get(chunk['chunk_id'], set()))
        linked_refs = sorted(chunk_to_refs.get(chunk['chunk_id'], set()))
        linked_params = params_by_chunk.get(chunk['chunk_id'], [])
        linked_results = results_by_chunk.get(chunk['chunk_id'], [])
        relation_types = chunk_rel_types.get(chunk['chunk_id'], [])

        relevant_text_parts = [claim or text]
        relevant_text_parts.extend(fig_lookup[f].get('caption','') for f in linked_figs if f in fig_lookup)
        relevant_text_parts.extend(tab_lookup[t].get('caption','') for t in linked_tabs if t in tab_lookup)
        relevant_text = ' '.join(relevant_text_parts)
        goal_score_raw, goal_hits = token_score(relevant_text, goal_terms, goal_phrase_terms)
        evidence_strength = score_evidence(linked_figs, linked_tabs, linked_refs, len(linked_params), len(linked_results), relation_types)
        current_score = current_work_signal(claim, page, chunk.get('section_title'), linked_figs, linked_tabs, linked_results, linked_refs)
        background_load = background_burden(claim, page, linked_figs, linked_tabs, linked_results, linked_refs)

        type_bonus = {
            'result': 0.34,
            'mechanism': 0.30,
            'method': 0.20 if goal_profile['method_focus'] else 0.02,
            'summary': 0.10,
            'discussion': 0.04,
            'background': -0.24,
        }.get(point_type, 0.0)
        boundary_bonus = {'result': 0.16, 'explanation': 0.12, 'inference': -0.02, 'unclear': -0.06, 'background_reference': -0.10}.get(boundary, 0.0)
        numeric_bonus = min(0.18, len(NUMERIC_RE.findall(claim)) * 0.04)
        direct_support_bonus = 0.14 if (linked_figs or linked_tabs or linked_results) else 0.0
        page_penalty = -0.12 if page <= 2 and not linked_figs and not linked_tabs and not linked_results else 0.0
        refs_only_penalty = -0.14 if linked_refs and not linked_figs and not linked_tabs and not linked_results and point_type != 'mechanism' else 0.0
        citation_like = bool(CITATION_RE.search(claim)) or ('et al' in claim.lower())
        current_work_like = bool(re.search(r'\b(this study|our|herein|in this work|present work)\b', claim, re.I))
        literature_penalty = -0.20 if (page <= 3 and len(linked_refs) >= 2 and BACKGROUND_CUES.search(claim.lower())) else 0.0
        history_penalty = -0.22 if (citation_like and re.search(r'\b(et al|introduced|reported|recent studies|ILSVRC|in 20\d{2})\b', claim, re.I) and not linked_figs and not linked_tabs and not linked_results) else 0.0
        current_work_penalty = -0.26 if (citation_like and not current_work_like and re.search(r'\b(et al|introduced|reported|recent studies|best performing network)\b', claim, re.I) and point_type in {'result','method'} ) else 0.0
        method_penalty = -0.16 if point_type == 'method' and not goal_profile['method_focus'] and not linked_results else 0.0
        meta_penalty = -0.18 * sentence_meta_penalty(claim)
        table_listing_penalty = -0.28 if (re.search(r'\b(given|listed|shown|summarized)\b', claim, re.I) and META_CUES.search(claim) and not COMPARISON_CUE_RE.search(claim) and len(NUMERIC_RE.findall(claim)) <= 1) else 0.0
        proxy_background_penalty = -0.30 if (re.search(r'\b(et al|previous studies|reported|recent studies)\b', claim, re.I) and not current_work_like and not linked_results and not linked_figs and not linked_tabs) else 0.0
        external_result_penalty = -0.34 if (re.search(r'\bet al\.?\b|\bas shown by\b', claim, re.I) and not CURRENT_WORK_CUES.search(claim)) else 0.0
        literature_explanation_penalty = -0.28 if (LITERATURE_CUES.search(claim) and PROXY_BACKGROUND_CUES.search(claim) and not CURRENT_WORK_CUES.search(claim)) else 0.0
        generic_statement_penalty = -0.24 if (GENERIC_STATEMENT_CUES.search(claim) and not CURRENT_WORK_CUES.search(claim) and not COMPARISON_CUE_RE.search(claim)) else 0.0
        formula_penalty = -0.34 if (FORMULA_EXPOSITION_CUES.search(claim) and not COMPARISON_CUE_RE.search(claim) and not RESULT_CUES.search(claim)) else 0.0
        visual_description_penalty = -0.22 if (VISUAL_DESCRIPTION_CUES.search(claim) and not COMPARISON_CUE_RE.search(claim) and not MECH_CUES.search(claim) and len(NUMERIC_RE.findall(claim)) < 2) else 0.0
        captionish_penalty = -0.30 if (CAPTIONISH_CUES.search(claim) and not COMPARISON_CUE_RE.search(claim) and not MECH_CUES.search(claim)) else 0.0
        panel_prefix_penalty = -0.26 if (PANEL_PREFIX_CUES.search(claim.strip()) and len(NUMERIC_RE.findall(claim)) < 2 and not COMPARISON_CUE_RE.search(claim)) else 0.0
        legendish_penalty = -0.40 if (LEGENDISH_CUES.search(claim) and not COMPARISON_CUE_RE.search(claim)) else 0.0
        model_reference_penalty = -0.42 if (MODEL_REFERENCE_CUES.search(claim) and not CURRENT_WORK_CUES.search(claim)) else 0.0
        definition_heavy_penalty = -0.42 if (DEFINITION_HEAVY_CUES.search(claim) and not CURRENT_WORK_CUES.search(claim)) else 0.0
        method_listing_penalty = -0.44 if (METHOD_LISTING_CUES.search(claim) and not goal_profile['method_focus']) else 0.0
        citation_leading_penalty = -0.46 if (re.match(r'^\s*\[?\d+\]?\s*(indicates?|shows?|reported|suggested)', claim, re.I) and not CURRENT_WORK_CUES.search(claim)) else 0.0
        process_bonus = 0.08 if goal_profile['process_focus'] and re.search(r'\b(flow|transport|cooling rate|heat input|welding direction|pool)\b', claim.lower()) else 0.0
        mechanism_bonus = 0.10 if goal_profile['mechanism_focus'] and point_type == 'mechanism' else 0.0
        performance_bonus = 0.10 if goal_profile['performance_focus'] and re.search(r'\b(hardness|wear|corrosion|accuracy|tensile|strength|loss)\b', claim.lower()) else 0.0
        image_bonus = 0.10 if goal_profile['image_focus'] and re.search(r'\b(image|patch|cnn|accuracy|recognition|dataset|augmentation)\b', claim.lower()) else 0.0
        current_work_bonus = 0.26 * current_score
        background_penalty = -0.34 * background_load
        raw_relevance = (
            0.11*min(goal_score_raw, 12) + 0.50*evidence_strength + type_bonus + boundary_bonus + numeric_bonus +
            direct_support_bonus + page_penalty + refs_only_penalty + literature_penalty + history_penalty + current_work_penalty + method_penalty +
            meta_penalty + table_listing_penalty + proxy_background_penalty + external_result_penalty + literature_explanation_penalty + generic_statement_penalty + formula_penalty + visual_description_penalty + captionish_penalty + panel_prefix_penalty + legendish_penalty + model_reference_penalty + definition_heavy_penalty + method_listing_penalty + citation_leading_penalty + process_bonus + mechanism_bonus + performance_bonus + image_bonus +
            current_work_bonus + background_penalty
        )
        relevance_score = round(1.0 / (1.0 + math.exp(-(raw_relevance - 0.90) * 2.5)), 4)
        analysis_confidence = round(min(1.0, 0.34 + 0.40*evidence_strength + 0.06*len(goal_hits) + 0.12*(1 if boundary in ('result','explanation') else 0)), 4)

        raw_writing_points.append({
            'raw_writing_point_id': f'rwp{idx:04d}',
            'source_chunk_id': chunk['chunk_id'],
            'page': chunk.get('page'),
            'section_id': chunk.get('section_id'),
            'section_title': chunk.get('section_title'),
            'point_type': point_type,
            'boundary_type': boundary,
            'boundary_note': boundary_note(boundary),
            'citation_role': classify_citation_role(point_type, claim, linked_refs, linked_figs, linked_tabs, linked_results),
            'claim': claim,
            'source_text': text,
            'causal_roles': build_causal_chain(claim, point_type),
            'goal_hits': goal_hits,
            'goal_alignment_note': goal_alignment_note(goal_hits, build_causal_chain(claim, point_type), point_type),
            'relevance_score': relevance_score,
            'evidence_strength': evidence_strength,
            'analysis_confidence': analysis_confidence,
            'current_work_score': round(current_score, 4),
            'background_burden': round(background_load, 4),
            'linked_figures': linked_figs,
            'linked_tables': linked_tabs,
            'linked_references': linked_refs,
            'linked_parameters': linked_params,
            'linked_results': linked_results,
            'relation_types': sorted(set(rt for rt in relation_types if rt)),
            'selection_reason': f"目标词命中 {len(goal_hits)} 个，图/表/结果支撑 {len(linked_figs)}/{len(linked_tabs)}/{len(linked_results)}。",
        })

    raw_ranked_points = sorted(raw_writing_points, key=lambda x: (x['relevance_score'], x['evidence_strength'], x['analysis_confidence']), reverse=True)
    writing_points = aggregate_writing_points(raw_ranked_points)
    top_points = choose_top_points(writing_points, topk=topk, goal_profile=goal_profile)
    cluster_boost = build_cluster_boost(evidence_clusters)

    ranked_figures = []
    for fig in figures:
        supporting = [wp for wp in writing_points if fig.get('figure_id') in wp.get('linked_figures', [])]
        best_wp = max((wp['relevance_score'] for wp in supporting), default=0.0)
        avg_wp = (sum(wp['relevance_score'] for wp in supporting) / len(supporting)) if supporting else 0.0
        cap_score, cap_hits = token_score(fig.get('caption', ''), goal_terms, goal_phrase_terms)
        result_cover = sum(1 for wp in supporting if wp.get('linked_results'))
        param_cover = sum(1 for wp in supporting if wp.get('linked_parameters'))
        fig_score = round(min(1.0, 0.48*best_wp + 0.18*avg_wp + 0.10*min(cap_score/8.0, 1.0) + 0.10*min(result_cover, 4)/4 + 0.06*min(param_cover, 4)/4 + 0.08*cluster_boost.get(f"figure::{fig.get('figure_id')}", 0.0)), 4)
        ranked_figures.append({
            'figure_id': fig.get('figure_id'),
            'page': fig.get('page'),
            'caption': fig.get('caption'),
            'relevance_score': fig_score,
            'supporting_writing_point_ids': [wp['writing_point_id'] for wp in supporting[:12]],
            'goal_hits': cap_hits,
            'selection_reason': f'由 {len(supporting)} 个写作点支撑，且图题对目标 {", ".join(cap_hits[:5]) if cap_hits else "弱命中"}。',
        })
    ranked_figures.sort(key=lambda x: x['relevance_score'], reverse=True)

    ranked_tables = []
    for tab in tables:
        supporting = [wp for wp in writing_points if tab.get('table_id') in wp.get('linked_tables', [])]
        best_wp = max((wp['relevance_score'] for wp in supporting), default=0.0)
        avg_wp = (sum(wp['relevance_score'] for wp in supporting) / len(supporting)) if supporting else 0.0
        cap_score, cap_hits = token_score(tab.get('caption', ''), goal_terms, goal_phrase_terms)
        numeric_bonus = min(0.12, 0.04 * len(NUMERIC_RE.findall(tab.get('caption', ''))))
        tab_score = round(min(1.0, 0.50*best_wp + 0.18*avg_wp + 0.10*min(cap_score/8.0, 1.0) + numeric_bonus + 0.08*cluster_boost.get(f"table::{tab.get('table_id')}", 0.0)), 4)
        ranked_tables.append({
            'table_id': tab.get('table_id'),
            'page': tab.get('page'),
            'caption': tab.get('caption'),
            'relevance_score': tab_score,
            'supporting_writing_point_ids': [wp['writing_point_id'] for wp in supporting[:12]],
            'goal_hits': cap_hits,
            'selection_reason': f'由 {len(supporting)} 个写作点支撑，表题数值信息较丰富。' if numeric_bonus else f'由 {len(supporting)} 个写作点支撑。',
        })
    ranked_tables.sort(key=lambda x: x['relevance_score'], reverse=True)

    ranked_references = []
    for ref in references:
        ref_number = ref.get('ref_number')
        rid = ref.get('ref_id') or (f'ref_{int(ref_number):03d}' if ref_number is not None else None)
        supporting = [wp for wp in writing_points if rid in wp.get('linked_references', [])]
        best_wp = max((wp['relevance_score'] for wp in supporting), default=0.0)
        avg_wp = (sum(wp['relevance_score'] for wp in supporting) / len(supporting)) if supporting else 0.0
        bg_bonus = 0.08 if any(wp['citation_role'] == 'background_reference' for wp in supporting) else 0.0
        ref_score = round(min(1.0, 0.56*best_wp + 0.20*avg_wp + 0.06*min(len(supporting), 6) + bg_bonus), 4)
        ranked_references.append({
            'ref_id': rid,
            'raw_marker': ref.get('raw_marker') or (f'[{int(ref_number)}]' if ref_number is not None else None),
            'entry_text': ref.get('entry_text') or ref.get('raw_text'),
            'relevance_score': ref_score,
            'supporting_writing_point_ids': [wp['writing_point_id'] for wp in supporting[:12]],
            'selection_reason': f'被 {len(supporting)} 个写作点调用。' + (' 主要承担背景引用。' if bg_bonus else ''),
        })
    ranked_references.sort(key=lambda x: x['relevance_score'], reverse=True)

    ranked_parameters = score_ranked_cards(parameter_cards, writing_points, goal_terms, goal_phrase_terms, 'parameter')
    ranked_results = score_ranked_cards(result_cards, writing_points, goal_terms, goal_phrase_terms, 'result')

    boundary_summary = dict(Counter(wp['boundary_type'] for wp in writing_points))

    selected_fig_ids = {fid for wp in top_points for fid in wp['linked_figures']}
    selected_ref_ids = {rid for wp in top_points for rid in wp['linked_references']}
    selected_tab_ids = {tid for wp in top_points for tid in wp['linked_tables']}
    selected_param_ids = {pid for wp in top_points for pid in wp['linked_parameters']}
    selected_result_ids = {rid for wp in top_points for rid in wp['linked_results']}
    if not selected_ref_ids:
        selected_ref_ids = {r['ref_id'] for r in ranked_references[:min(5, len(ranked_references))] if r.get('relevance_score', 0) >= 0.2}

    return {
        'goal': goal,
        'goal_profile': goal_profile,
        'raw_writing_points': raw_ranked_points,
        'writing_points': writing_points,
        'boundary_summary': boundary_summary,
        'ranked_figures': ranked_figures,
        'ranked_tables': ranked_tables,
        'ranked_references': ranked_references,
        'ranked_parameters': ranked_parameters,
        'ranked_results': ranked_results,
        'selected_writing_points': top_points,
        'selected_figures': [f for f in ranked_figures if f['figure_id'] in selected_fig_ids][:topk],
        'selected_images': [f for f in ranked_figures if f['figure_id'] in selected_fig_ids][:topk],
        'selected_references': [r for r in ranked_references if r['ref_id'] in selected_ref_ids][:max(topk, 20)],
        'selected_tables': [t for t in ranked_tables if t['table_id'] in selected_tab_ids][:topk],
        'selected_parameters': [p for p in ranked_parameters if p['parameter_id'] in selected_param_ids][:max(topk, 16)],
        'selected_results': [r for r in ranked_results if r['result_id'] in selected_result_ids][:max(topk, 16)],
        'stats_analysis': {
            'raw_writing_point_count': len(raw_writing_points),
            'writing_point_count': len(writing_points),
            'ranked_figure_count': len(ranked_figures),
            'ranked_table_count': len(ranked_tables),
            'ranked_reference_count': len(ranked_references),
            'ranked_parameter_count': len(ranked_parameters),
            'ranked_result_count': len(ranked_results),
            'selected_writing_point_count': len(top_points),
            'selected_figure_count': len([f for f in ranked_figures if f['figure_id'] in selected_fig_ids][:topk]),
            'selected_reference_count': len([r for r in ranked_references if r['ref_id'] in selected_ref_ids][:max(topk, 20)]),
            'selected_parameter_count': len([p for p in ranked_parameters if p['parameter_id'] in selected_param_ids][:max(topk, 16)]),
            'selected_result_count': len([r for r in ranked_results if r['result_id'] in selected_result_ids][:max(topk, 16)]),
        },
        'status': 'analysis_ready',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='07 AI-style analysis and relevance scoring over bound evidence network.')
    parser.add_argument('input_json', help='Input JSON from 02 bound evidence stage')
    parser.add_argument('output_json', help='Output JSON for analysis and relevance ranking')
    parser.add_argument('--goal', required=True, help='Current writing goal used for relevance-driven selection')
    parser.add_argument('--topk', type=int, default=12)
    args = parser.parse_args()

    bound = json.loads(Path(args.input_json).read_text(encoding='utf-8'))
    out = analyze_bound(bound, goal=args.goal, topk=args.topk)
    Path(args.output_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'status': out['status'],
        'raw_writing_point_count': out['stats_analysis']['raw_writing_point_count'],
        'writing_point_count': out['stats_analysis']['writing_point_count'],
        'selected_writing_point_count': out['stats_analysis']['selected_writing_point_count'],
        'selected_figure_count': out['stats_analysis']['selected_figure_count'],
        'selected_reference_count': out['stats_analysis']['selected_reference_count'],
        'selected_parameter_count': out['stats_analysis']['selected_parameter_count'],
        'selected_result_count': out['stats_analysis']['selected_result_count'],
        'top_claim_preview': out['selected_writing_points'][0]['claim'][:180] if out['selected_writing_points'] else ''
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
