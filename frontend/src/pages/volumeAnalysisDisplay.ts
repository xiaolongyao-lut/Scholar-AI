const VOLUME_INTERNAL_TEXT_PATTERN =
  /(?:\/(?:api|runtime|resources|pipeline|memory)\/|https?:\/\/|[A-Za-z]:[\\/]|api[_\s-]?key|authorization|bearer|token|secret|env=|env_refs|capability_[a-z0-9_]*|[{}[\]"`])/i;

const VOLUME_INTERNAL_IDENTIFIER_PATTERN = /^[a-z]+(?:_[a-z0-9]+){1,}$/i;

const WINDOWS_DRIVE_PATTERN = /^[A-Za-z]:[\\/]?$/;

function compactVolumeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

export function sanitizeVolumeVisibleText(value: string | null | undefined, fallback: string): string {
  const text = compactVolumeText(String(value ?? ''));
  const fallbackText = compactVolumeText(fallback) || '本地记录';
  if (!text || text.length > 160 || VOLUME_INTERNAL_TEXT_PATTERN.test(text) || VOLUME_INTERNAL_IDENTIFIER_PATTERN.test(text)) return fallbackText;
  return text;
}

export function formatVolumePathLabel(value: string | null | undefined, fallback = '本地目录'): string {
  const raw = compactVolumeText(String(value ?? ''));
  if (!raw || VOLUME_INTERNAL_TEXT_PATTERN.test(raw)) return fallback;

  const normalized = raw.replace(/\\/g, '/').replace(/\/+$/g, '');
  if (!normalized || WINDOWS_DRIVE_PATTERN.test(normalized)) return fallback;

  const parts = normalized.split('/').filter(Boolean);
  const lastSegment = parts.at(-1) ?? normalized;
  const visible = sanitizeVolumeVisibleText(lastSegment, fallback);
  return visible === fallback ? fallback : visible;
}

export function formatVolumeTaskSummary(folder: string | null | undefined, goal: string | null | undefined): string {
  const folderLabel = formatVolumePathLabel(folder, 'PDF 目录');
  const goalLabel = sanitizeVolumeVisibleText(goal, '分析目标');
  return `${folderLabel} · ${goalLabel}`;
}

export function formatVolumeActionError(error: unknown, fallback: string): string {
  if (error instanceof Error) {
    return sanitizeVolumeVisibleText(error.message, fallback);
  }
  if (typeof error === 'string') {
    return sanitizeVolumeVisibleText(error, fallback);
  }
  return compactVolumeText(fallback) || '操作失败，请稍后重试。';
}
