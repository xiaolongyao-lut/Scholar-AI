import type { JobStatus } from '@/types/runtime';

const INTERNAL_TEXT_PATTERNS: RegExp[] = [
  /\b(?:env(?:\s*=|_refs?)?|capability_[a-z0-9_]*|api[_\s-]?key|base[_\s-]?url|authorization|bearer|token|secret|fingerprint|sha256)\b/i,
  /\b(?:session_id|event_id|job_id|workspace_root|workspace_key|entry_cwd|parent_event_id|checkpoint_id)\b/i,
  /(?:^|\s)(?:\/api\/|\/runtime\/|\/resources\/|\/pipeline\/|\/memory\/)[^\s]*/i,
  /[A-Za-z]:[\\/][^\s]+/,
  /^\s*(?:\{[\s\S]*\}|\[[\s\S]*\])\s*$/,
  /^[a-z]+(?:_[a-z0-9]+){1,}$/i,
];

const COMPACT_TEXT_LIMIT = 180;

type TranslationFn = (key: string) => string;

const STATUS_LABEL_KEYS: Partial<Record<JobStatus, string>> = {
  created: 'writing.event.job_created',
  queued: 'writing.event.job_progress',
  started: 'writing.event.job_started',
  paused: 'writing.event.job_paused',
  in_progress: 'writing.event.job_progress',
  approval_pending: 'writing.event.approval_required',
  approval_rejected: 'writing.event.approval_rejected',
  completed: 'writing.event.job_completed',
  failed: 'writing.event.job_failed',
  cancelled: 'writing.event.job_cancelled',
};

const EVENT_LABEL_KEYS: Record<string, string> = {
  job_created: 'writing.event.job_created',
  job_started: 'writing.event.job_started',
  job_progress: 'writing.event.job_progress',
  tool_requested: 'writing.event.tool_requested',
  tool_blocked: 'writing.event.tool_blocked',
  approval_required: 'writing.event.approval_required',
  approval_granted: 'writing.event.approval_granted',
  approval_rejected: 'writing.event.approval_rejected',
  artifact_created: 'writing.event.artifact_created',
  artifact_updated: 'writing.event.artifact_updated',
  job_paused: 'writing.event.job_paused',
  job_resumed: 'writing.event.job_resumed',
  job_completed: 'writing.event.job_completed',
  job_failed: 'writing.event.job_failed',
  job_cancelled: 'writing.event.job_cancelled',
};

function isInternalRuntimeText(value: string): boolean {
  const normalized = value.trim();
  if (!normalized) return false;
  if (normalized.length > COMPACT_TEXT_LIMIT) return true;
  return INTERNAL_TEXT_PATTERNS.some((pattern) => pattern.test(normalized));
}

function compactRuntimeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

export function sanitizeRuntimeVisibleText(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback;
  const compact = compactRuntimeText(value);
  if (!compact || isInternalRuntimeText(compact)) return fallback;
  return compact;
}

export function formatWritingRuntimeError(error: unknown, fallback = '操作失败，请稍后重试。'): string {
  if (error instanceof Error) {
    return sanitizeRuntimeVisibleText(error.message, fallback);
  }
  if (typeof error === 'string') {
    return sanitizeRuntimeVisibleText(error, fallback);
  }
  return fallback;
}

export function describeRuntimeEventData(
  data: Record<string, unknown> | undefined,
  fallback: string,
): string {
  if (!data) return fallback;

  const preferredKeys = ['message', 'detail', 'error', 'output_text', 'text', 'reason'];
  for (const key of preferredKeys) {
    const visible = sanitizeRuntimeVisibleText(data[key], fallback);
    if (visible !== fallback) return visible;
  }

  return fallback;
}

export function formatRuntimeJobStatus(
  status: string | null | undefined,
  t: TranslationFn,
  fallbackKey = 'writing.event.job_progress',
): string {
  if (!status) return t(fallbackKey);
  const labelKey = STATUS_LABEL_KEYS[status as JobStatus] ?? fallbackKey;
  return t(labelKey);
}

export function formatRuntimeEventLabel(
  eventType: string | null | undefined,
  t: TranslationFn,
): string {
  if (!eventType) return t('writing.event.job_progress');
  return t(EVENT_LABEL_KEYS[eventType] ?? 'writing.event.job_progress');
}
