from __future__ import annotations

import re

ARCHITECTURE_LAYERS = {
    'constraints': '约束器：只定义目标、固定主线、命名规则、输出契约与硬规则，不直接调用工具。',
    'router': '调度器：只把用户需求和AI判断翻译为标准mode，先服从约束，再调工具。',
    'tools': '工具集：只执行extract/bind/select/pack/register/crop/build/deliver/word/fullchain。',
    'validators': '检查器：专门检查约束、调度、工具之间是否冲突，并检查输出契约。',
}

OPEN_FOCUS_STOPWORDS = {
    '提取', '抽取', '处理', '整理', '分析', '检查', '测试', '先', '正式', '文献', '文章', '论文',
    '根据', '围绕', '关注', '聚焦', '从', '针对', '角度', '方面', '以及', '还有', '先看', '先做',
    '材料', '主线', '不要', '偏离', '研究', '结果', '问题', '任务', '这篇', '那篇', '当前', '完整',
    'fullchain', 'extract', 'bind', 'select', 'pack', 'register', 'crop', 'build', 'deliver', 'word',
    'check', 'emit', '控制', 'ai', 'AI', '智能', '交叉领域'
}
OPEN_FOCUS_TRIGGER_RE = re.compile(r'(?:围绕|关注|聚焦|针对|从|面向|关于)([^，。；;,\.\n]{2,48})')
OPEN_FOCUS_TOKEN_RE = re.compile(r'[A-Za-z][A-Za-z0-9_\-]{2,24}|[一-鿿]{2,12}')


def infer_open_focus_points(command: str, explicit_goal: str = '', known_focus_keywords: set[str] | None = None) -> list[str]:
    known_focus_keywords = known_focus_keywords or set()
    text = f"{command or ''} {explicit_goal or ''}".strip()
    if not text:
        return []
    phrases = OPEN_FOCUS_TRIGGER_RE.findall(text) or [text]
    candidates: list[str] = []
    generic_fragments = [
        '根据', '围绕', '关注', '聚焦', '针对', '从', '面向', '关于', '先提取', '提取', '抽取',
        '处理', '整理', '分析', '检查', '测试', '生成', '并生成', '输出', '构建', '运行', '跑',
        '正式文献', '这篇', '文献', '文章', '论文',
        '构建目标导向写作材料包', '原文', '交付包', '验收Word', '验收word', '写作整合稿', '完整材料包', '生成验收Word', '生成验收word',
        '最小包', '云盘包', '入云盘', '可入云盘', '一路做到', '从提取一路做到', '整条跑完', '跑完整条'
    ]
    for phrase in phrases:
        clean = phrase
        for frag in generic_fragments:
            clean = clean.replace(frag, ' ')
        clean = re.sub(r"[“”\"'()（）\[\]{}<>]", ' ', clean)
        clean = re.sub(r'[、，,；;。./]+', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        for token in OPEN_FOCUS_TOKEN_RE.findall(clean):
            t = token.strip()
            t = re.sub(r'^[与和及并]+', '', t)
            if not t or t in OPEN_FOCUS_STOPWORDS:
                continue
            if any(kw in t for kw in known_focus_keywords if len(kw) >= 2):
                continue
            t_low = t.lower()
            if any(sw in t for sw in ('提取', '文献', '材料包', '交付包', '这篇', '正式', '当前', '验收', 'word', 'Word', '原文', '生成', '输出', '构建', '运行')):
                continue
            if t_low in {'scientific', 'machine', 'learning', 'digital', 'twin', 'ai', 'ml', 'am'}:
                continue
            if t in {'增材制造', '材料主问题', '原位监测'}:
                continue
            if t.startswith('并') or t.endswith('生成') or t.endswith('给我') or t.endswith('云盘'):
                continue
            if t in {'先把', '整条', '最后给我', '最后给我云盘'}:
                continue
            if len(t) <= 1:
                continue
            candidates.append(t)
    dedup: list[str] = []
    for item in candidates:
        if item not in dedup:
            dedup.append(item)
    return dedup[:6]
