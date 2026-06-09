import type { WritingJob } from '@/types/runtime';

const INTERNAL_JOB_TEXT_PATTERNS: RegExp[] = [
  /\/(?:api|runtime|resources|pipeline|memory)\/[^\s'"<>]+/i,
  /\b[A-Z]:\\[^\s'"<>]+/i,
  /\b(?:job|session|credential|capability|event|node|edge|chunk|material|skill|action)_id\b/i,
  /\bcapability_[a-z0-9_]*\b/i,
  /\b(?:env(?:\s*=|_refs?)?|api[_\s-]?key|base[_\s-]?url|authorization|bearer|secret|token|fingerprint|sha256)\b/i,
  /^\s*(?:\{[\s\S]*\}|\[[\s\S]*\])\s*$/,
  /^[a-z]+(?:_[a-z0-9]+){1,}$/i,
];

const JOB_KIND_LABELS: Record<string, string> = {
  prompt_action: '文本任务',
  skill_action: '技能任务',
  pipeline_run: '流程任务',
  approval: '审批任务',
  artifact_export: '导出任务',
  smart_read: '智能研读',
  discussion: '多智能体讨论',
  ai_review: 'AI 审稿',
  figure_load: '图表加载',
};

function compactJobText(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

export function sanitizeJobVisibleText(
  value: string | null | undefined,
  fallback: string,
  limit = 160,
): string {
  const compact = compactJobText(String(value ?? ''));
  const fallbackText = compactJobText(fallback);
  if (!compact || compact.length > limit || INTERNAL_JOB_TEXT_PATTERNS.some((pattern) => pattern.test(compact))) {
    return fallbackText;
  }
  return compact;
}

export function formatJobError(error: unknown, fallback = '任务操作失败，请稍后重试。'): string {
  if (error instanceof Error) {
    return sanitizeJobVisibleText(error.message, fallback);
  }
  if (typeof error === 'string') {
    return sanitizeJobVisibleText(error, fallback);
  }
  return fallback;
}

export function formatJobRuntimeError(value: string | null | undefined): string | undefined {
  if (!value?.trim()) return undefined;
  return sanitizeJobVisibleText(value, '任务执行失败，详细诊断已记录到本地日志。');
}

export function formatJobName(job: Pick<WritingJob, 'kind' | 'input_text'>): string {
  const kindLabel = JOB_KIND_LABELS[String(job.kind ?? '')] ?? '写作任务';
  const input = sanitizeJobVisibleText(job.input_text, '', 48);
  if (!input) return kindLabel;
  return `${kindLabel} · ${input}`;
}
