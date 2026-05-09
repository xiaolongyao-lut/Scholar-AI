/**
 * Resolve the API base URL for browser and desktop-like execution contexts.
 *
 * Why:
 * The browser dev server should reuse Vite's same-origin proxy, while desktop
 * or file-based shells still need a direct fallback to the local Python API.
 */
import { readEnv } from './env.ts';

const trimTrailingSlash = (value: string): string => value.replace(/\/+$/, '');

const getWindowAwareFallback = (): string => {
  if (typeof window === 'undefined') {
    return 'http://127.0.0.1:8000';
  }

  const protocol = window.location.protocol;
  if (protocol === 'http:' || protocol === 'https:') {
    return '';
  }

  return 'http://127.0.0.1:8000';
};

export const getApiBaseUrl = (): string => {
  const configuredValue = readEnv('VITE_API_BASE_URL');

  if (configuredValue.length > 0) {
    return trimTrailingSlash(configuredValue);
  }

  return getWindowAwareFallback();
};
