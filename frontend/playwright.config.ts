import { defineConfig } from '@playwright/test';

/**
 * Playwright configuration for frontend E2E smoke tests (TASK-179/TASK-192).
 *
 * Uses a local Vite dev server (E2E config: no backend proxy) with mock API responses.
 * Tests focus on user-visible behavior: role/text/test-id locators
 * and web-first assertions per Playwright best practices.
 *
 * Windows stability notes (TASK-192):
 * - webServer.timeout raised to 60s for cold Vite starts on Windows
 * - reuseExistingServer=true to avoid port conflicts from zombie processes
 * - actionTimeout added to guard against animation-related stalls
 * - Uses vite.config.e2e.ts without backend proxy to prevent ECONNREFUSED hangs
 * - Single project to avoid context/server lifecycle issues
 * - Tests are alphabetically ordered: smoke.spec.ts → skill-manager.spec.ts is fine
 *   because file naming ensures smoke runs first, warming up Vite's module graph
 */
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3100',
    browserName: 'chromium',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },
  webServer: {
    command: 'npx vite --config vite.config.e2e.ts',
    port: 3100,
    timeout: 60_000,
    reuseExistingServer: true,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
