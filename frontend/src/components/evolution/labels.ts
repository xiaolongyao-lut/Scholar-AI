// Chinese label maps for Evolution UI.
//
// Co-located with components (not under services/) because these are pure
// presentation strings — components own them, the wire layer is enum-only.
// See docs/plans/active/2026-05-18-evolution-s5-review-ui-plan.md
// §Product Framing Copy for the locked vocabulary.

import type {
  CandidateMemoryType,
  CandidateRiskLevel,
  CandidateSourceType,
  CandidateStatus,
} from '../../services/evolutionTypes';
import type { StatusTone } from '../common/StatusPill';

export const SOURCE_LABELS: Record<CandidateSourceType, string> = {
  inspiration: '灵感',
  discussion: '多专家讨论',
  rag_answer: '智能研读',
  runtime_job: '写作任务',
  skill_run: '流程执行',
  pdf_annotation: 'PDF 笔记',
  mcp_tool_use: '工具调用',
  manual: '手动录入',
  curator: '系统整理',
};

export const MEMORY_TYPE_LABELS: Record<CandidateMemoryType, string> = {
  user_preference: '用户偏好',
  project_fact: '项目事实',
  literature_procedure: '文献流程',
  domain_knowledge: '领域知识',
  evidence_rule: '证据规则',
  agent_role_lesson: '角色经验',
  tool_reliability: '工具可靠性',
  skill_draft: '流程草稿',
};

export const STATUS_LABELS: Record<CandidateStatus, string> = {
  captured: '待复审',
  pending: '待复审',
  accepted: '已保存',
  rejected: '已忽略',
  snoozed: '稍后再看',
  expired: '已过期',
  promoted_to_memory: '已应用到长期记忆',
  promoted_to_skill_draft: '流程草稿已生成',
  rolled_back: '已撤销',
  blocked: '不能保存',
};

export const STATUS_TONES: Record<CandidateStatus, StatusTone> = {
  captured: 'warning',
  pending: 'warning',
  accepted: 'success',
  rejected: 'neutral',
  snoozed: 'info',
  expired: 'neutral',
  promoted_to_memory: 'success',
  promoted_to_skill_draft: 'success',
  rolled_back: 'neutral',
  blocked: 'danger',
};

export const RISK_LABELS: Record<CandidateRiskLevel, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
};

export const RISK_TONES: Record<CandidateRiskLevel, StatusTone> = {
  low: 'neutral',
  medium: 'warning',
  high: 'danger',
};

const INTERNAL_REASON_PATTERN =
  /(?:[a-z]+_[a-z0-9_]+|[A-Z][A-Z0-9_]{2,}|[=:{}[\]"'`]|\/[a-z0-9._/-]+|sha256:|wing_evolution)/;

const INTERNAL_VISIBLE_TEXT_PATTERN =
  /(?:env=|env_refs|candidate_id|source_id|workspace_id|project_id|dedupe_hash|rollback_ref|api[_\s-]?key|base[_\s-]?url|authorization|bearer|token|secret|https?:\/\/|\/api\/[^\s"'<>，。；,;)]*|\/runtime\/[^\s"'<>，。；,;)]*|[A-Za-z]:\\[^\s"'<>]*|sha256:|\b[a-z]+(?:_[a-z0-9]+){1,}\b|[{}[\]"`]|[A-Za-z0-9+/]{32,}={0,2})/i;

export function sanitizeEvolutionUserText(value: unknown, fallback: string): string {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw || raw.length > 220 || INTERNAL_VISIBLE_TEXT_PATTERN.test(raw)) {
    return fallback;
  }
  return raw;
}

const SENSITIVE_DETAIL_TEXT_PATTERN =
  /(?:api[_\s-]?key|base[_\s-]?url|authorization|bearer|token|secret|https?:\/\/|\/api\/[^\s"'<>，。；,;)]*|[A-Za-z]:\\[^\s"'<>]*|sha256:)/i;

export function sanitizeEvolutionDetailText(value: unknown, fallback: string, maxChars = 1800): string {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) {
    return fallback;
  }
  const normalized = raw.replace(/\u0000/g, '').replace(/\r\n/g, '\n');
  if (SENSITIVE_DETAIL_TEXT_PATTERN.test(normalized)) {
    return fallback;
  }
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
}

export function formatEvolutionError(value: unknown, fallback = '操作失败，请稍后重试。'): string {
  const raw = value instanceof Error ? value.message : typeof value === 'string' ? value : '';
  return sanitizeEvolutionUserText(raw, fallback);
}

export const SOURCE_TRIGGER_DESCRIPTIONS: Record<CandidateSourceType, string> = {
  inspiration: '灵感生成时发现可复用的偏好、事实或写作方法。',
  discussion: '多专家讨论产出结论后，系统提取可复用的角色经验或项目事实。',
  rag_answer: '智能研读回答问题时，系统从可靠证据和你的反馈中提取候选经验。',
  runtime_job: '写作、导出、分析等任务运行完成后，系统记录可复用的流程经验。',
  skill_run: 'Skill 执行后，系统记录可复用的步骤、约束或失败经验。',
  pdf_annotation: 'PDF 批注或笔记沉淀后，系统提取可复用的阅读经验。',
  mcp_tool_use: 'MCP 工具调用完成后，系统记录工具可靠性或使用边界。',
  manual: '由用户手动录入，等待复审后保存。',
  curator: '系统整理已有候选时生成，需要人工复审。',
};

export function friendlyDecisionReason(raw: string | null | undefined): string {
  const trimmed = (raw ?? '').trim();
  if (!trimmed) return '（无说明）';
  if (trimmed === 'ui_reject_permanent') return '用户标记为永久忽略';
  if (trimmed === 'ui_snooze_7d') return '用户稍后再看（7 天）';
  if (trimmed.startsWith('secret_scan:')) return '被密钥扫描拦截';
  if (trimmed.startsWith('dedupe:')) return '重复候选，已合并';
  if (trimmed.startsWith('curator:')) return '系统整理后标记为需要复审';
  if (trimmed.startsWith('promoted:')) {
    const lower = trimmed.toLowerCase();
    if (lower.includes('skill')) return '已生成流程草稿';
    if (lower.includes('memory')) return '已应用到长期记忆';
    return '已完成应用';
  }
  if (INTERNAL_REASON_PATTERN.test(trimmed)) {
    return '系统记录了一条处置说明，原始诊断信息已隐藏';
  }
  return trimmed;
}

// Evidence state labels used by product-facing copy:
// "有证据 / 证据不足 / 重复 / 风险较高"
export type EvidenceState = 'has_evidence' | 'no_evidence' | 'duplicate' | 'high_risk';

export const EVIDENCE_STATE_LABELS: Record<EvidenceState, string> = {
  has_evidence: '有证据',
  no_evidence: '证据不足',
  duplicate: '重复',
  high_risk: '风险较高',
};

export const EVIDENCE_STATE_TONES: Record<EvidenceState, StatusTone> = {
  has_evidence: 'success',
  no_evidence: 'warning',
  duplicate: 'neutral',
  high_risk: 'danger',
};

// Decide which evidence pill to render. Risk wins over evidence presence
// because a high-risk candidate is the most important thing to flag.
export function deriveEvidenceState(args: {
  status: CandidateStatus;
  risk_level: CandidateRiskLevel;
  evidence_count: number;
  decision_reason: string | null;
}): EvidenceState {
  if (args.risk_level === 'high') return 'high_risk';
  if (args.status === 'blocked' && /duplicate|dedup/i.test(args.decision_reason ?? '')) {
    return 'duplicate';
  }
  if (args.evidence_count > 0) return 'has_evidence';
  return 'no_evidence';
}
