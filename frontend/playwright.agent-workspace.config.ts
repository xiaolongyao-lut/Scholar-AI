import { defineConfig } from '@playwright/test';

/**
 * Browser smoke gate for Agent Workspace recovery visibility.
 *
 * This intentionally avoids the ignored broad E2E harness and uses a dedicated
 * Vite server so requirement drilldown acceptance stays reproducible.
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: /agent-workspace-requirement-drilldown\.spec\.ts/,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3121',
    browserName: 'chromium',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },
  webServer: {
    command: 'npx vite --config vite.agent-workspace.e2e.ts',
    port: 3121,
    timeout: 60_000,
    reuseExistingServer: true,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
