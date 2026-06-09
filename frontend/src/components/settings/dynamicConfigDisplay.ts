const INTERNAL_EXPOSURE_PATTERN =
  /(?:\/api\/|https?:\/\/|[A-Za-z]:\\|api[_\s-]?key|base[_\s-]?url|authorization|bearer|token|secret|env=|env_refs|server_id|server_slug|credential_id|credential_refs|capability_[a-z_]+|capability_id|fingerprint|sha256:|[{}[\]"`])/i;

const INTERNAL_IDENTIFIER_TOKEN_PATTERN =
  /\b(?:[A-Z][A-Z0-9]+_[A-Z0-9_]+|(?:env|credential|capability|server|provider|api|base|token|secret|fingerprint|session|source|project|workspace|candidate|audit|job)_[a-z0-9_]+)\b/;

const RAW_IDENTIFIER_PATTERN =
  /^(?:[A-Z][A-Z0-9]+_[A-Z0-9_]+|[a-z][a-z0-9]*_[a-z0-9_]+|[a-z0-9]+(?:[-_][a-z0-9]+){2,})$/;

const MAX_VISIBLE_TEXT_LENGTH = 120;

interface DynamicVisibleTextOptions {
  hideIdentifierLike?: boolean;
  maxLength?: number;
}

export interface DynamicConfigFieldMetadata {
  id?: unknown;
  label?: unknown;
  env?: unknown;
  description?: unknown;
}

/**
 * Bounds manifest-provided UI text before it becomes product copy.
 *
 * Input: unknown manifest value. Output: non-empty Chinese fallback or safe text.
 * Raw routes, credentials, env names, local paths, and structured blobs are rejected.
 */
export function sanitizeDynamicManifestText(
  value: unknown,
  fallback: string,
  options: DynamicVisibleTextOptions = {},
): string {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) return fallback;
  const maxLength = options.maxLength ?? MAX_VISIBLE_TEXT_LENGTH;
  if (raw.length > maxLength) return fallback;
  if (INTERNAL_EXPOSURE_PATTERN.test(raw)) return fallback;
  if (INTERNAL_IDENTIFIER_TOKEN_PATTERN.test(raw)) return fallback;
  if (options.hideIdentifierLike === true && RAW_IDENTIFIER_PATTERN.test(raw)) return fallback;
  return raw;
}

export function formatDynamicConfigFieldLabel(value: unknown, index: number): string {
  return sanitizeDynamicManifestText(value, `配置项 ${index + 1}`, { hideIdentifierLike: true });
}

export function formatDynamicCredentialLabel(value: unknown, index?: number): string {
  const fallback = typeof index === 'number' ? `凭证 ${index + 1}` : '所需凭证';
  return sanitizeDynamicManifestText(value, fallback, { hideIdentifierLike: true });
}

export function formatDynamicOptionLabel(value: unknown, index: number): string {
  return sanitizeDynamicManifestText(value, `选项 ${index + 1}`, { hideIdentifierLike: false });
}

export function formatDynamicDescription(value: unknown): string | null {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) return null;
  const sanitized = sanitizeDynamicManifestText(raw, '', { hideIdentifierLike: false, maxLength: 180 });
  return sanitized.length > 0 ? sanitized : null;
}

function readClassifierText(value: unknown): string {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

export function getDynamicConfigManualEntryHint(field: DynamicConfigFieldMetadata): string {
  const classifier = [
    readClassifierText(field.id),
    readClassifierText(field.label),
    readClassifierText(field.env),
    readClassifierText(field.description),
  ].filter(Boolean).join(' ');

  if (/(?:api[_\s-]?key|token|secret|password|authorization|bearer|访问密钥|密码|令牌)/i.test(classifier)) {
    return '敏感值不要填在普通配置里，请在凭证绑定中选择已保存凭证。';
  }

  if (/(?:api|base[_\s-]?url|endpoint|provider|model|openai|gemini|ollama|dashscope|rerank|embedding|vision|image|picture|接口|服务|地址|提供商|模型|向量|重排|视觉|图像|图片|生图)/i.test(classifier)) {
    return '可选择预设，也可按任意兼容服务文档手动填写；访问密钥请在凭证绑定中选择。';
  }

  return '可选择预设，也可手动填写此包支持的取值。';
}
