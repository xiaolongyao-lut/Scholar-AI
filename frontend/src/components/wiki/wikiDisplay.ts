const WIKI_INTERNAL_TEXT_PATTERN =
  /(?:\/api\/|https?:\/\/|[A-Za-z]:\\|[{}[\]"`]|agent[\s_-]?result|api[_\s-]?key|base[_\s-]?url|authorization|bearer|token|secret|env=|env_refs|fingerprint|sha256:)/i;

const WIKI_INTERNAL_IDENTIFIER_PATTERN =
  /\b(?:[A-Z][A-Z0-9]+_[A-Z0-9_]+|[a-z]+(?:_[a-z0-9]+){2,}|[a-f0-9]{8,}|(?:source|project|workspace|material|chunk|page|graph|review|queue|node|edge|session|credential|capability)_[a-z0-9_]+)\b/;

/**
 * Bounds knowledge UI text before it is rendered outside developer diagnostics.
 *
 * Input: backend or markdown-derived value. Output: safe text or fallback.
 * Local paths, routes, structured blobs, credential words, and raw ids are hidden.
 */
export function sanitizeWikiVisibleText(value: unknown, fallback: string): string {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) return fallback;
  if (raw.length > 180) return fallback;
  if (WIKI_INTERNAL_TEXT_PATTERN.test(raw)) return fallback;
  if (WIKI_INTERNAL_IDENTIFIER_PATTERN.test(raw)) return fallback;
  return raw;
}

export function formatWikiPageLabel(value: unknown, fallback = '知识页面'): string {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) return fallback;
  const normalized = raw.replace(/\\/g, '/');
  const tail = normalized.split('/').filter(Boolean).at(-1) ?? normalized;
  const withoutExtension = tail.replace(/\.(md|markdown)$/i, '').trim();
  return sanitizeWikiVisibleText(withoutExtension, fallback);
}

export function formatWikiWarning(value: unknown): string {
  const raw = typeof value === 'string' ? value : '';
  if (raw.includes('Wiki integration is disabled')) {
    return '知识库尚未启用。';
  }
  const normalized = raw.toLowerCase();
  if (normalized.includes('source manifest hash differs')) {
    return '来源清单已变化，检索索引需要重新生成。';
  }
  if (normalized.includes('page count differs')) {
    return '页面数量与检索索引不一致。';
  }
  if (normalized.includes('row count differs')) {
    return '检索索引记录数不一致。';
  }
  if (normalized.includes('does not record a source manifest hash')) {
    return '检索索引缺少来源清单记录。';
  }
  return sanitizeWikiVisibleText(raw, '检测到一项需要处理的知识库状态。');
}

export function formatWikiError(value: unknown, fallback = '读取知识库信息失败，请稍后重试。'): string {
  return sanitizeWikiVisibleText(value, fallback);
}
