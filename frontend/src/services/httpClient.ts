import axios, { AxiosHeaders } from 'axios';
import type {
  AxiosError,
  AxiosInstance,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios';
import { getApiBaseUrl } from './apiBaseUrl.ts';

const DEFAULT_TIMEOUT_MS = 30_000;
const DEFAULT_RETRY_BASE_DELAY_MS = 250;
const DEFAULT_RETRY_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504]);
const DEFAULT_RETRY_METHODS = new Set(['get', 'head', 'options']);

export interface ApiClientRetryOptions {
  maxAttempts?: number;
  baseDelayMs?: number;
  statuses?: readonly number[];
  methods?: readonly string[];
}

export interface ApiClientOptions {
  baseURL?: string;
  timeoutMs?: number;
  authTokenProvider?: () => string | null;
  retry?: ApiClientRetryOptions;
}

export interface ApiClientErrorShape {
  message: string;
  status: number | null;
  code: string | null;
  method: string | null;
  url: string | null;
  retryable: boolean;
  details: unknown;
}

/**
 * Error shape used by shared service clients.
 *
 * Why:
 * Axios errors include transport, config, and response details in provider-
 * specific fields. Service consumers need one stable, non-sensitive shape while
 * still preserving the original cause for diagnostics.
 */
export class ApiClientError extends Error {
  public readonly status: number | null;
  public readonly code: string | null;
  public readonly method: string | null;
  public readonly url: string | null;
  public readonly retryable: boolean;
  public readonly details: unknown;
  public readonly cause: unknown;

  public constructor(shape: ApiClientErrorShape, cause: unknown) {
    if (!shape.message.trim()) {
      throw new Error('ApiClientError requires a non-empty message.');
    }
    super(shape.message);
    this.name = 'ApiClientError';
    this.status = shape.status;
    this.code = shape.code;
    this.method = shape.method;
    this.url = shape.url;
    this.retryable = shape.retryable;
    this.details = shape.details;
    this.cause = cause;
  }
}

interface NormalizedRetryOptions {
  maxAttempts: number;
  baseDelayMs: number;
  statuses: ReadonlySet<number>;
  methods: ReadonlySet<string>;
}

const clampPositiveInteger = (
  value: number | undefined,
  fallback: number,
  fieldName: string,
): number => {
  if (value === undefined) {
    return fallback;
  }
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`${fieldName} must be a positive integer.`);
  }
  return value;
};

const normalizeRetryOptions = (
  retry: ApiClientRetryOptions | undefined,
): NormalizedRetryOptions | null => {
  if (retry === undefined) {
    return null;
  }

  const maxAttempts = clampPositiveInteger(retry.maxAttempts, 2, 'retry.maxAttempts');
  const baseDelayMs = clampPositiveInteger(
    retry.baseDelayMs,
    DEFAULT_RETRY_BASE_DELAY_MS,
    'retry.baseDelayMs',
  );
  const statuses = retry.statuses === undefined
    ? DEFAULT_RETRY_STATUSES
    : new Set(retry.statuses);
  const methods = retry.methods === undefined
    ? DEFAULT_RETRY_METHODS
    : new Set(retry.methods.map((method) => method.trim().toLowerCase()));

  if (statuses.size === 0) {
    throw new Error('retry.statuses must contain at least one HTTP status.');
  }
  for (const status of statuses) {
    if (!Number.isInteger(status) || status < 100 || status > 599) {
      throw new Error('retry.statuses must contain valid HTTP status codes.');
    }
  }
  if (methods.size === 0 || methods.has('')) {
    throw new Error('retry.methods must contain non-empty HTTP methods.');
  }

  return { maxAttempts, baseDelayMs, statuses, methods };
};

const getAxiosError = (error: unknown): AxiosError<unknown> | null => (
  axios.isAxiosError<unknown>(error) ? error : null
);

const getStatus = (error: unknown): number | null => (
  getAxiosError(error)?.response?.status ?? null
);

const getMethod = (error: unknown): string | null => {
  const method = getAxiosError(error)?.config?.method;
  return typeof method === 'string' && method.trim() ? method.toUpperCase() : null;
};

const getUrl = (error: unknown): string | null => {
  const url = getAxiosError(error)?.config?.url;
  return typeof url === 'string' && url.trim() ? url : null;
};

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
);

const readStringField = (
  value: Record<string, unknown>,
  fieldName: string,
): string | null => {
  const fieldValue = value[fieldName];
  return typeof fieldValue === 'string' && fieldValue.trim() ? fieldValue.trim() : null;
};

const formatValidationDetail = (detail: readonly unknown[]): string | null => {
  const messages = detail
    .map((entry) => {
      if (!isRecord(entry)) {
        return typeof entry === 'string' && entry.trim() ? entry.trim() : null;
      }
      const message = readStringField(entry, 'msg') ?? readStringField(entry, 'message');
      const location = entry.loc;
      if (!message) {
        return null;
      }
      if (!Array.isArray(location) || location.length === 0) {
        return message;
      }
      const path = location
        .map((part) => String(part))
        .filter((part) => part.trim())
        .join('.');
      return path ? `${path}: ${message}` : message;
    })
    .filter((message): message is string => message !== null);

  if (messages.length === 0) {
    return null;
  }
  return messages.slice(0, 3).join('; ');
};

const getResponseMessage = (data: unknown): string | null => {
  if (typeof data === 'string' && data.trim()) {
    return data.trim();
  }
  if (Array.isArray(data)) {
    return formatValidationDetail(data);
  }
  if (!isRecord(data)) {
    return null;
  }

  const directMessage = readStringField(data, 'message') ?? readStringField(data, 'error');
  if (directMessage) {
    return directMessage;
  }

  const detail = data.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }
  if (Array.isArray(detail)) {
    return formatValidationDetail(detail);
  }
  if (isRecord(detail)) {
    return readStringField(detail, 'message')
      ?? readStringField(detail, 'error')
      ?? readStringField(detail, 'reason')
      ?? null;
  }
  return null;
};

const isRetryableStatus = (
  status: number | null,
  retry: NormalizedRetryOptions | null,
): boolean => status !== null && retry !== null && retry.statuses.has(status);

const isRetryableMethod = (
  method: string | undefined,
  retry: NormalizedRetryOptions,
): boolean => retry.methods.has((method ?? 'get').toLowerCase());

const sleep = (delayMs: number): Promise<void> => (
  new Promise((resolve) => {
    globalThis.setTimeout(resolve, delayMs);
  })
);

const toApiClientError = (
  error: unknown,
  retry: NormalizedRetryOptions | null,
): ApiClientError => {
  const axiosError = getAxiosError(error);
  const status = axiosError?.response?.status ?? null;
  const message = getResponseMessage(axiosError?.response?.data)
    ?? axiosError?.message
    ?? (error instanceof Error ? error.message : 'API request failed.');

  return new ApiClientError(
    {
      message,
      status,
      code: typeof axiosError?.code === 'string' ? axiosError.code : null,
      method: getMethod(error),
      url: getUrl(error),
      retryable: isRetryableStatus(status, retry),
      details: axiosError?.response?.data ?? null,
    },
    error,
  );
};

/**
 * Create a shared Axios client for frontend service modules.
 *
 * Args:
 *   options: Optional base URL, timeout, bearer-token provider, and retry
 *     policy. Retries are disabled unless `retry` is explicitly provided.
 *
 * Returns:
 *   Axios instance with consistent base URL, timeout, auth injection, optional
 *   idempotent retry, and normalized error wrapping.
 *
 * Why shared:
 *   All API modules should use this factory to ensure consistent retry logic,
 *   error normalization, and timeout handling. Direct axios.create() or bare
 *   axios.get/post bypasses these guarantees.
 */
export function createApiClient(options: ApiClientOptions = {}): AxiosInstance {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new Error('timeoutMs must be a positive finite number.');
  }

  const retry = normalizeRetryOptions(options.retry);
  const attempts = new WeakMap<object, number>();
  const client = axios.create({
    baseURL: options.baseURL ?? getApiBaseUrl(),
    timeout: timeoutMs,
  });

  if (options.authTokenProvider !== undefined) {
    client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
      const token = options.authTokenProvider?.();
      if (token !== null && token !== undefined && token.trim()) {
        const headers = AxiosHeaders.from(config.headers);
        headers.set('Authorization', `Bearer ${token}`);
        config.headers = headers;
      }
      return config;
    });
  }

  client.interceptors.response.use(
    (response: AxiosResponse<unknown>) => response,
    async (error: unknown) => {
      const axiosError = getAxiosError(error);
      const config = axiosError?.config;
      if (retry !== null && config !== undefined && isRetryableMethod(config.method, retry)) {
        const nextAttempt = (attempts.get(config) ?? 1) + 1;
        if (nextAttempt <= retry.maxAttempts && retry.statuses.has(getStatus(error) ?? 0)) {
          attempts.set(config, nextAttempt);
          await sleep(retry.baseDelayMs * 2 ** (nextAttempt - 2));
          return client.request(config);
        }
      }

      return Promise.reject(toApiClientError(error, retry));
    },
  );

  return client;
}

/**
 * Create a default API client with standard retry policy for idempotent requests.
 *
 * Why:
 * Most service modules need the same base configuration. This avoids repeating
 * createApiClient({ retry: { maxAttempts: 3 } }) in every file.
 *
 * Usage:
 *   import { createDefaultApiClient } from './httpClient';
 *   const client = createDefaultApiClient();
 *   const { data } = await client.get('/endpoint');
 */
export function createDefaultApiClient(options: Omit<ApiClientOptions, 'retry'> = {}): AxiosInstance {
  return createApiClient({
    ...options,
    retry: {
      maxAttempts: 3,
      baseDelayMs: DEFAULT_RETRY_BASE_DELAY_MS,
      statuses: Array.from(DEFAULT_RETRY_STATUSES),
      methods: Array.from(DEFAULT_RETRY_METHODS),
    },
  });
}
