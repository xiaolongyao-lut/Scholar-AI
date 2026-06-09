import axios, { AxiosHeaders } from 'axios';
import type {
  AxiosInstance,
  AxiosStatic,
  CreateAxiosDefaults,
  InternalAxiosRequestConfig,
} from 'axios';
import { readEnv } from './env';

const CAPABILITY_BOOTSTRAP_KEY = '__LITASSIST_API_CAPABILITY__';
const FALLBACK_HEADER_NAME = 'X-LitAssist-Capability';
const DEFAULT_FILE_SHELL_API_ORIGIN = 'http://127.0.0.1:8000';
const BACKEND_ROUTE_PREFIXES = new Set([
  'actions',
  'agent',
  'api',
  'autopilot',
  'capabilities',
  'chat',
  'evolution',
  'inspiration',
  'llm',
  'memory',
  'pipeline',
  'recovery',
  'resources',
  'run_action',
  'runtime',
  'sampling',
  'skill_packs',
  'skills',
  'transform_result',
  'volumes',
]);
let installed = false;

interface LocalApiCapabilityBootstrap {
  header: string;
  token: string;
}

declare global {
  interface Window {
    __LITASSIST_API_CAPABILITY__?: unknown;
  }
}

function isCapabilityBootstrap(value: unknown): value is LocalApiCapabilityBootstrap {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.header === 'string'
    && record.header.trim().length > 0
    && typeof record.token === 'string'
    && record.token.trim().length > 0
  );
}

function readCapabilityBootstrap(): LocalApiCapabilityBootstrap | null {
  if (typeof window === 'undefined') {
    return null;
  }
  const value = window[CAPABILITY_BOOTSTRAP_KEY];
  if (!isCapabilityBootstrap(value)) {
    return null;
  }
  return {
    header: value.header.trim() || FALLBACK_HEADER_NAME,
    token: value.token.trim(),
  };
}

function currentLocationHref(): string {
  if (typeof window === 'undefined') {
    return 'http://127.0.0.1:8000/';
  }
  return window.location.href;
}

function currentLocationOrigin(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return window.location.origin;
}

function configuredApiOrigin(): string | null {
  const configuredValue = readEnv('VITE_API_BASE_URL').replace(/\/+$/, '');
  if (configuredValue.length > 0) {
    const configuredUrl = parseRequestUrl(configuredValue);
    return configuredUrl?.origin ?? null;
  }
  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol;
    if (protocol !== 'http:' && protocol !== 'https:') {
      return DEFAULT_FILE_SHELL_API_ORIGIN;
    }
  }
  return null;
}

function parseRequestUrl(value: string): URL | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  try {
    return new URL(normalized, currentLocationHref());
  } catch {
    return null;
  }
}

function isBackendRoutePath(pathname: string): boolean {
  const normalizedPath = pathname.replace(/^\/+/, '');
  if (!normalizedPath) {
    return false;
  }
  const firstSegment = normalizedPath.split('/', 1)[0] ?? '';
  return BACKEND_ROUTE_PREFIXES.has(firstSegment);
}

function isLoopbackBackendOrigin(url: URL): boolean {
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return false;
  }
  const hostname = url.hostname.toLowerCase();
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1' || hostname === '[::1]';
}

function isAllowedCapabilityOrigin(url: URL): boolean {
  const currentOrigin = currentLocationOrigin();
  if (currentOrigin !== null && url.origin === currentOrigin) {
    return true;
  }
  const apiOrigin = configuredApiOrigin();
  if (apiOrigin !== null && url.origin === apiOrigin) {
    return true;
  }
  return isLoopbackBackendOrigin(url);
}

function shouldAttachCapabilityToUrl(url: URL | null): boolean {
  if (url === null) {
    return false;
  }
  return isBackendRoutePath(url.pathname) && isAllowedCapabilityOrigin(url);
}

function isAbsoluteAxiosUrl(url: string): boolean {
  return /^[a-z][a-z\d+\-.]*:/i.test(url) || url.startsWith('//');
}

function joinAxiosUrl(baseURL: string, url: string): string | null {
  const normalizedBase = baseURL.trim();
  const normalizedUrl = url.trim();
  if (!normalizedBase && !normalizedUrl) {
    return null;
  }
  if (!normalizedBase || isAbsoluteAxiosUrl(normalizedUrl)) {
    return normalizedUrl;
  }
  if (!normalizedUrl) {
    return normalizedBase;
  }
  return `${normalizedBase.replace(/\/+$/, '')}/${normalizedUrl.replace(/^\/+/, '')}`;
}

function resolveAxiosRequestUrl(config: InternalAxiosRequestConfig): URL | null {
  const url = typeof config.url === 'string' ? config.url : '';
  const baseURL = typeof config.baseURL === 'string' ? config.baseURL : '';
  const joinedUrl = joinAxiosUrl(baseURL, url);
  return joinedUrl === null ? null : parseRequestUrl(joinedUrl);
}

function resolveFetchRequestUrl(input: RequestInfo | URL): URL | null {
  if (input instanceof URL) {
    return input;
  }
  if (typeof Request !== 'undefined' && input instanceof Request) {
    return parseRequestUrl(input.url);
  }
  if (typeof input === 'string') {
    return parseRequestUrl(input);
  }
  return null;
}

function attachCapabilityHeader(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const capability = readCapabilityBootstrap();
  if (capability === null) {
    return config;
  }
  if (!shouldAttachCapabilityToUrl(resolveAxiosRequestUrl(config))) {
    return config;
  }
  const headers = AxiosHeaders.from(config.headers);
  if (!headers.has(capability.header)) {
    headers.set(capability.header, capability.token);
  }
  config.headers = headers;
  return config;
}

function installAxiosCapabilityInterceptor(instance: AxiosInstance): void {
  instance.interceptors.request.use(attachCapabilityHeader);
}

function installFetchCapabilityInterceptor(): void {
  if (typeof window === 'undefined' || typeof window.fetch !== 'function') {
    return;
  }
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const capability = readCapabilityBootstrap();
    if (capability === null) {
      return originalFetch(input, init);
    }
    if (!shouldAttachCapabilityToUrl(resolveFetchRequestUrl(input))) {
      return originalFetch(input, init);
    }
    const nextInit: RequestInit = { ...(init ?? {}) };
    const requestHeaders = typeof Request !== 'undefined' && input instanceof Request ? input.headers : undefined;
    const headers = new Headers(nextInit.headers ?? requestHeaders);
    if (!headers.has(capability.header)) {
      headers.set(capability.header, capability.token);
    }
    nextInit.headers = headers;
    return originalFetch(input, nextInit);
  };
}

function patchAxiosCreate(axiosStatic: AxiosStatic): void {
  const originalCreate = axiosStatic.create.bind(axiosStatic);
  axiosStatic.create = (config?: CreateAxiosDefaults): AxiosInstance => {
    const instance = originalCreate(config);
    installAxiosCapabilityInterceptor(instance);
    return instance;
  };
}

/**
 * Install process-local API capability propagation for browser requests.
 *
 * Why:
 * The token is injected into the backend-served HTML shell at runtime and is
 * not part of the Vite bundle. Intercepting both default Axios, created Axios
 * instances, and fetch keeps existing service modules compatible.
 */
export function installLocalApiCapabilityPropagation(): void {
  if (installed) {
    return;
  }
  installed = true;
  installAxiosCapabilityInterceptor(axios);
  patchAxiosCreate(axios);
  installFetchCapabilityInterceptor();
}
