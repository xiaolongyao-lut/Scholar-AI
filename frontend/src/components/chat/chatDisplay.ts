const GENERIC_CHAT_ERROR = '生成失败，请检查配置或稍后重试。';
const CREDENTIAL_CHAT_ERROR = '访问凭证不可用，请在 API 配置中检查后重试。';
const MODEL_CHAT_ERROR = '模型或服务地址不可用，请检查供应商、服务地址和模型是否匹配。';
const NETWORK_CHAT_ERROR = '请求超时或网络不可用，请稍后重试。';

const SECRET_WORD_PATTERN = /\b(api[\s_-]*key|authorization|bearer|token|secret|password|credential)\b/i;
const MODEL_NOT_FOUND_PATTERN = /\b(invalidendpointormodel\.notfound|model_not_found|model or endpoint|model.+not found)\b/i;
const NETWORK_ERROR_PATTERN = /\b(timeout|timed out|network error|econnaborted|err_network|failed to fetch)\b/i;
const STATUS_ERROR_PATTERN = /\b(status code|http)\s*(4\d\d|5\d\d)\b/i;
const ROUTE_OR_URL_PATTERN = /\bhttps?:\/\/\S+|(?:^|[\s"'([{])\/(?:api|inspiration|mcp|chat|agent|settings|resources|runtime)\S*/i;
const WINDOWS_PATH_PATTERN = /\b[A-Za-z]:\\[^\s"'<>]+|\\\\[^\s"'<>]+/;
const JSONISH_PATTERN = /[{[][^{}\[\]\n]{0,600}["'][^{}\[\]\n]{0,600}:[^{}\[\]\n]{0,600}[}\]]/;
const ENV_OR_INTERNAL_PATTERN = /\benv\s*=|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\b(?:capability|provider|credential|session|runtime|route|tool|mcp|api|env)_[a-z0-9_]+\b/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readVisibleString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim().replace(/\u0000/g, '');
  return trimmed || null;
}

function extractChatErrorMessage(error: unknown): string {
  if (isRecord(error) && isRecord(error.response)) {
    const data = error.response.data;
    if (isRecord(data)) {
      if (isRecord(data.error)) {
        const nested = readVisibleString(data.error.message);
        if (nested) return nested;
      }
      const detail = data.detail;
      const detailText = readVisibleString(detail);
      if (detailText) return detailText;
      if (detail !== undefined) return JSON.stringify(detail);
    }
    const status = typeof error.response.status === 'number' ? error.response.status : null;
    if (status) return `HTTP ${status}`;
  }
  if (error instanceof Error) return error.message;
  return String(error ?? '');
}

function containsTechnicalDetail(message: string): boolean {
  return (
    ROUTE_OR_URL_PATTERN.test(message) ||
    WINDOWS_PATH_PATTERN.test(message) ||
    JSONISH_PATTERN.test(message) ||
    ENV_OR_INTERNAL_PATTERN.test(message)
  );
}

interface ChatVisibleTextOptions {
  maxLength?: number;
}

interface ChatVisibleErrorOptions {
  fallback?: string;
}

/**
 * Returns bounded chat copy for history titles, previews, and search snippets.
 *
 * The input can be backend-generated or restored from old local history. Values
 * that look like diagnostics, env labels, paths, JSON, or internal identifiers
 * are replaced so old transcripts cannot leak implementation details in the UI.
 */
export function sanitizeChatVisibleText(
  value: unknown,
  fallback: string,
  options: ChatVisibleTextOptions = {},
): string {
  const visible = readVisibleString(value);
  if (!visible || containsTechnicalDetail(visible)) {
    return fallback;
  }
  const maxLength = options.maxLength;
  if (typeof maxLength === 'number' && Number.isFinite(maxLength) && maxLength > 0 && visible.length > maxLength) {
    return `${visible.slice(0, maxLength).trimEnd()}…`;
  }
  return visible;
}

/**
 * Converts unknown chat/runtime failures into bounded user-facing copy.
 *
 * The input may be an Error, axios-like response object, or arbitrary thrown
 * value. Diagnostic strings are classified but never rendered raw.
 */
export function formatChatVisibleError(error: unknown, options: ChatVisibleErrorOptions = {}): string {
  const fallback = readVisibleString(options.fallback) ?? GENERIC_CHAT_ERROR;
  const message = extractChatErrorMessage(error);
  if (NETWORK_ERROR_PATTERN.test(message)) return NETWORK_CHAT_ERROR;
  if (SECRET_WORD_PATTERN.test(message)) return CREDENTIAL_CHAT_ERROR;
  if (MODEL_NOT_FOUND_PATTERN.test(message)) return MODEL_CHAT_ERROR;
  if (STATUS_ERROR_PATTERN.test(message)) return fallback;
  if (containsTechnicalDetail(message)) return fallback;
  const visible = readVisibleString(message);
  return visible ?? fallback;
}
