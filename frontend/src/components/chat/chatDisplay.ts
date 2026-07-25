const GENERIC_CHAT_ERROR = '生成失败，请检查配置或稍后重试。';
const CREDENTIAL_CHAT_ERROR = '访问凭证不可用，请在 API 配置中检查后重试。';
const MODEL_CHAT_ERROR = '模型或服务地址不可用，请检查供应商、服务地址和模型是否匹配。';
const NETWORK_CHAT_ERROR = '请求超时或网络不可用，请稍后重试。';
const TOOL_CALL_UNSUPPORTED_CHAT_ERROR = '当前 API 代理不支持工具调用，请在设置中测试工具调用能力，或改用普通问答链路。';

const SECRET_WORD_PATTERN = /\b(api[\s_-]*key|authorization|bearer|token|secret|password|credential)\b/i;
const MODEL_NOT_FOUND_PATTERN = /\b(invalidendpointormodel\.notfound|model_not_found|model or endpoint|model.+not found)\b/i;
const NETWORK_ERROR_PATTERN = /\b(timeout|timed out|network error|econnaborted|err_network|failed to fetch)\b/i;
const STATUS_ERROR_PATTERN = /\b(status code|http)\s*(4\d\d|5\d\d)\b/i;
const TOOL_CALL_UNSUPPORTED_PATTERN = /\b(tool|function)\s*calling\b.*\bnot\s+supported\b|\bnot\s+support(?:ed)?\b.*\b(tool|function)\s*calling\b/i;
const ROUTE_OR_URL_PATTERN = /\bhttps?:\/\/\S+|(?:^|[\s"'([{])\/(?:api|inspiration|mcp|chat|agent|settings|resources|runtime)\S*/i;
const WINDOWS_PATH_PATTERN = /\b[A-Za-z]:\\[^\s"'<>]+|\\\\[^\s"'<>]+/;
const JSONISH_PATTERN = /[{[][^{}\[\]\n]{0,600}["'][^{}\[\]\n]{0,600}:[^{}\[\]\n]{0,600}[}\]]/;
const ENV_OR_INTERNAL_PATTERN = /\benv\s*=|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\b(?:capability|provider|credential|session|runtime|route|tool|mcp|api|env)_[a-z0-9_]+\b/i;
const LEADING_QUESTION_LINE_PATTERN =
  /^\s*(?:#{1,6}\s*)?(?:(?:\*\*|__)\s*)?(?:问题|用户问题|question|user\s+question)(?:(?:\*\*|__)\s*)?[:：][^\r\n]*(?:\r?\n|$)/i;
const QUESTION_PREFIXES = [
  '问题：',
  '问题:',
  '用户问题：',
  '用户问题:',
  'question:',
  'user question:',
] as const;
const EVIDENCE_SUMMARY_HEADING_PATTERN =
  /(?:^|\r?\n)\s*(?:#{1,6}\s*)?(?:(?:\*\*|__)\s*)?(?:证据摘要|evidence\s+summary)\s*(?:(?:\*\*|__)\s*)?(?:[:：]\s*(?:(?:\*\*|__)\s*)?|(?=\r?\n|$))/i;
const EVIDENCE_SUMMARY_PREFIXES = ['证据摘要', 'evidence summary'] as const;
const LEADING_BRIDGE_LINE_PATTERNS: readonly RegExp[] = [
  /^\s*证据已准备[，,]\s*等待(?:外部)?智能体回答。?\s*(?:\r?\n|$)/,
  /^\s*已切换为外部智能体回答模式。?\s*(?:\r?\n|$)/,
  /^\s*文献助手未调用内部聊天模型；已完成本地检索，并把证据交给\s*Codex\/Claude\s*等外部智能体生成最终回答。?\s*(?:\r?\n|$)/,
  /^\s*外部智能体应优先使用\s*evidence_refs\s*\/\s*context_metadata\.chunks\s*中的引用和\s*chunk_id\s*组织最终回答。?\s*(?:\r?\n|$)/,
  /^\s*检索结果\s*[:：][^\r\n]*(?:\r?\n|$)/,
  /^\s*提示\s*[:：]\s*上下文已按当前研读档位截断。?\s*(?:\r?\n|$)/,
];
const BRIDGE_PREFIXES = [
  '证据已准备，等待智能体回答。',
  '证据已准备，等待外部智能体回答。',
  '已切换为外部智能体回答模式。',
  '文献助手未调用内部聊天模型；已完成本地检索，并把证据交给 Codex/Claude 等外部智能体生成最终回答。',
  '外部智能体应优先使用 evidence_refs / context_metadata.chunks 中的引用和 chunk_id 组织最终回答。',
  '检索结果：',
  '提示：上下文已按当前研读档位截断。',
] as const;

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

function normalizedLeadingArtifactLine(value: string): string {
  const firstLine = value.split(/\r?\n/, 1)[0] ?? '';
  return firstLine
    .trimStart()
    .replace(/^#{1,6}\s*/, '')
    .replace(/^(?:\*\*|__)\s*/, '');
}

function stripLeadingAssistantArtifacts(value: string): string {
  let remaining = value.trim();
  for (let pass = 0; pass < 8 && remaining; pass += 1) {
    let next = remaining.replace(LEADING_QUESTION_LINE_PATTERN, '').trimStart();
    for (const pattern of LEADING_BRIDGE_LINE_PATTERNS) {
      next = next.replace(pattern, '').trimStart();
    }
    if (next === remaining) break;
    remaining = next;
  }
  return remaining.trim();
}

function partialEvidenceSummaryHeadingStart(value: string): number | null {
  const lastNewline = value.lastIndexOf('\n');
  const lineStart = lastNewline >= 0 ? lastNewline + 1 : 0;
  const candidate = value
    .slice(lineStart)
    .trimStart()
    .replace(/^#{1,6}\s*/, '')
    .replace(/^(?:\*\*|__)\s*/, '')
    .replace(/(?:\*\*|__)\s*$/, '')
    .trim()
    .toLowerCase();
  if (!candidate) return null;
  return EVIDENCE_SUMMARY_PREFIXES.some((prefix) => prefix.startsWith(candidate))
    ? lineStart
    : null;
}

/**
 * Return only the answer body that is safe to place in a normal chat bubble.
 *
 * The function accepts the full text accumulated so far during streaming.
 * Incomplete leading question labels are withheld so they never flash before
 * the first answer token arrives.
 */
export function sanitizeAssistantVisibleContent(value: string): string {
  const raw = value.replace(/\u0000/g, '').trim();
  if (!raw) return '';
  const withoutLeadingArtifacts = stripLeadingAssistantArtifacts(raw);
  const evidenceSummaryStart = withoutLeadingArtifacts.search(EVIDENCE_SUMMARY_HEADING_PATTERN);
  const summaryStart = evidenceSummaryStart >= 0
    ? evidenceSummaryStart
    : partialEvidenceSummaryHeadingStart(withoutLeadingArtifacts);
  const answerBody = summaryStart !== null
    ? withoutLeadingArtifacts.slice(0, summaryStart).trim()
    : withoutLeadingArtifacts;
  if (answerBody !== raw) return answerBody;
  const leadingLine = normalizedLeadingArtifactLine(raw);
  const normalizedLeadingLine = leadingLine.toLowerCase();
  if (
    QUESTION_PREFIXES.some((prefix) => prefix.startsWith(normalizedLeadingLine))
    || BRIDGE_PREFIXES.some((prefix) => prefix.toLowerCase().startsWith(normalizedLeadingLine))
  ) {
    return '';
  }
  return raw;
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
  if (TOOL_CALL_UNSUPPORTED_PATTERN.test(message)) return TOOL_CALL_UNSUPPORTED_CHAT_ERROR;
  if (STATUS_ERROR_PATTERN.test(message)) return fallback;
  if (containsTechnicalDetail(message)) return fallback;
  const visible = readVisibleString(message);
  return visible ?? fallback;
}
