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
 * specific fields. Service consumers need one stable, non-secret shape while
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
  const message = axiosError?.message
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
