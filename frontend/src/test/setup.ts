import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll, afterAll } from 'vitest';

// jsdom does not provide matchMedia; stub a default light/no-reduced-motion env.
// Individual tests may stub `window.matchMedia` per-case via `vi.stubGlobal`.
if (typeof window !== 'undefined' && typeof window.matchMedia === 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

if (typeof window !== 'undefined' && typeof window.HTMLElement.prototype.scrollIntoView !== 'function') {
  Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: () => undefined,
  });
}

afterEach(() => {
  cleanup();
});

const originalConsoleWarn = console.warn;

beforeAll(() => {
  console.warn = (message?: unknown, ...args: unknown[]) => {
    if (
      typeof message === 'string'
      && message.includes('React Router Future Flag Warning')
    ) {
      return;
    }
    originalConsoleWarn(message, ...args);
  };
});

afterAll(() => {
  console.warn = originalConsoleWarn;
});
