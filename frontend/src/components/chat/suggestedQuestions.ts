import type { ProjectChunkResource, WritingMaterialResource } from '@/types/resources';

export type SuggestedQuestionKind =
  | 'review'
  | 'welding'
  | 'materials'
  | 'mechanics'
  | 'method'
  | 'application'
  | 'general';

export interface SuggestedQuestion {
  id: string;
  label: string;
  question: string;
  kind: SuggestedQuestionKind;
}

interface KeywordRule {
  kind: SuggestedQuestionKind;
  keywords: string[];
}

const QUESTION_LIMIT = 5;
const CONTEXT_CHAR_LIMIT = 18_000;

const REVIEW_KEYWORDS = [
  'review',
  'survey',
  'overview',
  'progress',
  'state of the art',
  'recent advances',
  '综述',
  '进展',
  '研究现状',
  '发展现状',
];

const KEYWORD_RULES: KeywordRule[] = [
  {
    kind: 'welding',
    keywords: [
      'weld',
      'welding',
      'laser welding',
      'friction stir',
      'arc welding',
      'tig',
      'mig',
      '熔焊',
      '焊接',
      '激光焊',
      '搅拌摩擦焊',
      '电弧焊',
      '接头',
      '热影响区',
    ],
  },
  {
    kind: 'mechanics',
    keywords: [
      'fatigue',
      'static load',
      'dynamic load',
      'cyclic load',
      'impact',
      'fracture',
      'crack',
      'stress',
      'strain',
      'creep',
      'tension',
      'compression',
      '疲劳',
      '静载',
      '动载',
      '循环载荷',
      '冲击',
      '断裂',
      '裂纹',
      '应力',
      '应变',
      '拉伸',
      '压缩',
    ],
  },
  {
    kind: 'method',
    keywords: [
      'model',
      'algorithm',
      'simulation',
      'finite element',
      'machine learning',
      'neural network',
      'optimization',
      '模型',
      '算法',
      '仿真',
      '有限元',
      '机器学习',
      '神经网络',
      '优化',
    ],
  },
  {
    kind: 'materials',
    keywords: [
      'alloy',
      'steel',
      'aluminum',
      'titanium',
      'composite',
      'microstructure',
      'grain',
      'phase',
      'hardness',
      '材料',
      '合金',
      '钢',
      '铝',
      '钛',
      '复合材料',
      '显微组织',
      '晶粒',
      '相变',
      '硬度',
    ],
  },
  {
    kind: 'application',
    keywords: [
      'case study',
      'industrial',
      'application',
      'prototype',
      'device',
      'process window',
      '工程应用',
      '案例',
      '工业',
      '应用',
      '原型',
      '工艺窗口',
    ],
  },
];

function normalizeText(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value.replace(/\s+/g, ' ').trim();
}

function visibleMaterialTitle(material: WritingMaterialResource | null): string {
  return normalizeText(material?.title || material?.title_en) || '这篇文献';
}

function chunkText(chunk: ProjectChunkResource): string {
  return normalizeText(chunk.content ?? chunk.text ?? chunk.title ?? '');
}

function buildContextText(
  material: WritingMaterialResource | null,
  chunks: ProjectChunkResource[],
): string {
  const parts = [
    material?.title,
    material?.title_en,
    material?.summary,
    material?.summary_en,
    ...(material?.focus_points ?? []),
    ...(material?.focus_points_en ?? []),
    ...chunks.slice(0, 16).map(chunkText),
  ];
  return parts.map(normalizeText).filter(Boolean).join(' ').slice(0, CONTEXT_CHAR_LIMIT);
}

function keywordScore(text: string, keywords: string[]): number {
  const lower = text.toLowerCase();
  return keywords.reduce((score, keyword) => (
    keywordMatches(lower, keyword) ? score + 1 : score
  ), 0);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function keywordMatches(lowerText: string, keyword: string): boolean {
  const normalized = keyword.toLowerCase().trim();
  if (!normalized) return false;
  if (/^[a-z0-9][a-z0-9\s-]*$/i.test(normalized)) {
    const pattern = new RegExp(`(^|[^a-z0-9])${escapeRegExp(normalized)}([^a-z0-9]|$)`, 'i');
    return pattern.test(lowerText);
  }
  return lowerText.includes(normalized);
}

function detectQuestionKind(contextText: string): SuggestedQuestionKind {
  const reviewScore = keywordScore(contextText, REVIEW_KEYWORDS);
  if (reviewScore > 0) return 'review';
  const scores = new Map<SuggestedQuestionKind, number>(
    KEYWORD_RULES.map((rule) => [rule.kind, keywordScore(contextText, rule.keywords)]),
  );
  if ((scores.get('welding') ?? 0) > 0) return 'welding';
  if ((scores.get('mechanics') ?? 0) > 0) return 'mechanics';
  if ((scores.get('method') ?? 0) > 0) return 'method';
  if ((scores.get('materials') ?? 0) > 0) return 'materials';
  if ((scores.get('application') ?? 0) > 0) return 'application';
  const ranked = Array.from(scores.entries())
    .map(([kind, score]) => ({ kind, score }))
    .sort((a, b) => b.score - a.score);
  const best = ranked[0];
  if (best && best.score > 0) return best.kind;
  return 'general';
}

function dedupeQuestions(questions: SuggestedQuestion[]): SuggestedQuestion[] {
  const seen = new Set<string>();
  const result: SuggestedQuestion[] = [];
  for (const question of questions) {
    const key = question.question.trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(question);
    if (result.length >= QUESTION_LIMIT) break;
  }
  return result;
}

function reviewQuestions(title: string): SuggestedQuestion[] {
  return [
    {
      id: 'review-map',
      label: '梳理对象',
      question: `${title} 主要梳理了哪些研究对象、材料体系或应用场景？请按类别列出来。`,
      kind: 'review',
    },
    {
      id: 'review-methods',
      label: '技术路线',
      question: '这篇综述把哪些实验方法、建模方法或工艺路线放在一起比较？各自适合什么问题？',
      kind: 'review',
    },
    {
      id: 'review-consensus',
      label: '共识分歧',
      question: '文中总结出了哪些稳定共识？哪些结论还存在分歧或证据不足？',
      kind: 'review',
    },
    {
      id: 'review-gap',
      label: '研究空白',
      question: '作者认为下一步最值得做的研究空白是什么？这些空白分别缺少什么证据？',
      kind: 'review',
    },
  ];
}

function weldingQuestions(title: string): SuggestedQuestion[] {
  return [
    {
      id: 'welding-material-process',
      label: '材料与焊法',
      question: `${title} 研究了哪些材料或接头形式？使用了哪些焊接方式或关键工艺参数？`,
      kind: 'welding',
    },
    {
      id: 'welding-parameters',
      label: '参数影响',
      question: '哪些焊接参数最影响组织、缺陷、强度或疲劳性能？文中给出的证据是什么？',
      kind: 'welding',
    },
    {
      id: 'welding-microstructure',
      label: '组织缺陷',
      question: '热影响区、熔合区或搅拌区发生了什么组织变化？这些变化怎么影响失效？',
      kind: 'welding',
    },
    {
      id: 'welding-application',
      label: '工程边界',
      question: '这项焊接研究适合哪些工程场景？还有哪些材料、厚度、载荷或环境条件没有覆盖？',
      kind: 'welding',
    },
  ];
}

function mechanicsQuestions(title: string): SuggestedQuestion[] {
  return [
    {
      id: 'mechanics-load',
      label: '载荷类型',
      question: `${title} 研究的是静载、疲劳、冲击、循环载荷还是断裂问题？对应的评价指标是什么？`,
      kind: 'mechanics',
    },
    {
      id: 'mechanics-failure',
      label: '失效机制',
      question: '主要失效模式是什么？裂纹、塑性变形、界面失效或疲劳损伤从哪里开始？',
      kind: 'mechanics',
    },
    {
      id: 'mechanics-method',
      label: '测试仿真',
      question: '文中用了哪些实验测试或仿真方法？边界条件、样品形状和载荷设置是否合理？',
      kind: 'mechanics',
    },
    {
      id: 'mechanics-design',
      label: '设计启发',
      question: '如果要把结论用于结构设计，哪些参数最应该控制？哪些结论不能直接外推？',
      kind: 'mechanics',
    },
  ];
}

function materialQuestions(title: string): SuggestedQuestion[] {
  return [
    {
      id: 'materials-system',
      label: '材料体系',
      question: `${title} 研究了什么材料体系、成分或处理状态？对照组是怎么设置的？`,
      kind: 'materials',
    },
    {
      id: 'materials-method',
      label: '表征方法',
      question: '作者用了哪些表征或性能测试方法？每种方法分别证明了什么？',
      kind: 'materials',
    },
    {
      id: 'materials-mechanism',
      label: '性能机制',
      question: '组织、相组成、缺陷或界面变化如何解释性能变化？证据链是否闭合？',
      kind: 'materials',
    },
    {
      id: 'materials-limit',
      label: '适用边界',
      question: '这套材料结论适用于哪些温度、载荷、环境或加工条件？哪些条件还没有验证？',
      kind: 'materials',
    },
  ];
}

function methodQuestions(title: string): SuggestedQuestion[] {
  return [
    {
      id: 'method-problem',
      label: '解决问题',
      question: `${title} 提出的方法主要解决了什么具体问题？输入、输出和评价指标是什么？`,
      kind: 'method',
    },
    {
      id: 'method-baseline',
      label: '对比基线',
      question: '它和已有方法、模型或工艺相比改进在哪里？对比实验是否公平？',
      kind: 'method',
    },
    {
      id: 'method-data',
      label: '数据条件',
      question: '方法依赖哪些数据、参数或假设？在小样本、噪声或外部数据下是否可靠？',
      kind: 'method',
    },
    {
      id: 'method-transfer',
      label: '可迁移性',
      question: '如果换一种材料、结构或实验场景，这个方法最可能在哪些环节失效？',
      kind: 'method',
    },
  ];
}

function applicationQuestions(title: string): SuggestedQuestion[] {
  return [
    {
      id: 'application-scenario',
      label: '应用场景',
      question: `${title} 面向什么工程或产业场景？实际约束条件有哪些？`,
      kind: 'application',
    },
    {
      id: 'application-process',
      label: '实施路径',
      question: '从实验结果到实际应用，中间还需要哪些工艺、设备、成本或可靠性验证？',
      kind: 'application',
    },
    {
      id: 'application-risk',
      label: '落地风险',
      question: '这项方案的主要失效风险、质量控制难点或规模化边界是什么？',
      kind: 'application',
    },
    {
      id: 'application-next',
      label: '下一步实验',
      question: '如果继续做这个方向，最应该补哪三个验证实验？每个实验要回答什么问题？',
      kind: 'application',
    },
  ];
}

function generalQuestions(title: string): SuggestedQuestion[] {
  return [
    {
      id: 'general-object',
      label: '研究对象',
      question: `${title} 具体研究了什么对象、问题和场景？请不要泛泛总结，按“对象-方法-结果”列出来。`,
      kind: 'general',
    },
    {
      id: 'general-method',
      label: '方法设计',
      question: '作者用了哪些实验、仿真、统计或理论方法？这些方法分别支撑了哪个结论？',
      kind: 'general',
    },
    {
      id: 'general-evidence',
      label: '证据链',
      question: '文中最关键的证据是哪几条？每条证据对应的图表、段落或实验结果是什么？',
      kind: 'general',
    },
    {
      id: 'general-limit',
      label: '局限边界',
      question: '这篇文章哪些结论可以直接借鉴？哪些结论受样本、参数、环境或方法假设限制？',
      kind: 'general',
    },
  ];
}

function questionsForKind(kind: SuggestedQuestionKind, title: string): SuggestedQuestion[] {
  if (kind === 'review') return reviewQuestions(title);
  if (kind === 'welding') return weldingQuestions(title);
  if (kind === 'mechanics') return mechanicsQuestions(title);
  if (kind === 'method') return methodQuestions(title);
  if (kind === 'application') return applicationQuestions(title);
  if (kind === 'materials') return materialQuestions(title);
  return generalQuestions(title);
}

export function buildSuggestedQuestions(
  material: WritingMaterialResource | null,
  chunks: ProjectChunkResource[],
): SuggestedQuestion[] {
  const title = visibleMaterialTitle(material);
  const contextText = buildContextText(material, chunks);
  const kind = detectQuestionKind(contextText);
  const primary = questionsForKind(kind, title);
  const fallback = kind === 'general' ? [] : generalQuestions(title);
  return dedupeQuestions([...primary, ...fallback]);
}
