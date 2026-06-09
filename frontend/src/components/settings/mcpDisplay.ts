import { type McpTransport } from '@/services/mcpApi';

export const MCP_TRANSPORT_LABELS: Record<McpTransport, string> = {
  stdio: '本地进程',
  streamable_http: '网络服务',
};

const INTERNAL_TEXT_PATTERN =
  /(?:env_refs|env=|server_id|server_slug|tool_call_id|install_record|credential_id|credential_refs|workspace_root|entry_cwd|fingerprint|sha256|capability_[a-z0-9_]+|api[\s_-]*key|base[\s_-]*url|authorization|bearer|token|secret|password|credential|\/api\/[^\s"'<>，。；,;)]*|\/runtime\/[^\s"'<>，。；,;)]*|\/resources\/[^\s"'<>，。；,;)]*|[A-Za-z]:[\\/][^\s"'<>]*)/i;

const RAW_IDENTIFIER_DISPLAY_PATTERN =
  /(?:^mcp[_-]|[_]|^[a-z0-9]+(?:-[a-z0-9]+)+$|^[a-z]+_[a-z0-9_]+$|^[a-z]{1,4}_[a-z0-9_]+$)/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function extractErrorMessage(exc: unknown): string {
  if (isRecord(exc) && isRecord(exc.response)) {
    const response = exc.response;
    if (isRecord(response.data)) {
      const detail = response.data.detail;
      if (typeof detail === 'string') {
        return detail;
      }
      if (isRecord(detail) && typeof detail.message === 'string') {
        return detail.message;
      }
      const error = response.data.error;
      if (typeof error === 'string') {
        return error;
      }
      if (isRecord(error) && typeof error.message === 'string') {
        return error.message;
      }
      if (typeof response.data.message === 'string') {
        return response.data.message;
      }
    }
    if (typeof response.status === 'number') {
      return `请求失败，状态码 ${response.status}`;
    }
  }
  if (exc instanceof Error) return exc.message;
  if (typeof exc === 'string') return exc;
  return '';
}

/**
 * Sanitizes backend/user-visible MCP text so raw local paths, credentials,
 * API routes, and internal field names are not rendered as product copy.
 */
export function sanitizeMcpVisibleText(value: unknown, fallback: string): string {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) return fallback;
  if (INTERNAL_TEXT_PATTERN.test(raw)) return fallback;
  if ((raw.startsWith('{') && raw.endsWith('}')) || (raw.startsWith('[') && raw.endsWith(']'))) {
    return fallback;
  }
  return raw;
}

/**
 * Converts MCP names that look like raw ids/slugs into stable display labels.
 */
export function sanitizeMcpDisplayLabel(value: unknown, fallback: string): string {
  const visible = sanitizeMcpVisibleText(value, fallback);
  if (visible === fallback) return fallback;
  if (RAW_IDENTIFIER_DISPLAY_PATTERN.test(visible.trim())) return fallback;
  return visible;
}

/**
 * Converts unknown MCP action failures into a bounded Chinese message.
 */
export function formatMcpActionError(exc: unknown, fallback = '操作失败，请稍后重试。'): string {
  return sanitizeMcpVisibleText(extractErrorMessage(exc), fallback);
}
