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
  rag_answer: '文献问答',
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

// Evidence state derived per plan §Product Framing Copy:
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
