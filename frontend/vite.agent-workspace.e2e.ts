import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

// Ensure dev routes are accessible during e2e smoke runs.
// Vite injects process.env.VITE_* into import.meta.env at serve time.
process.env.VITE_ENABLE_DEV_ROUTES = '1';

/**
 * Isolated Vite config for the Agent Workspace browser smoke.
 *
 * The test owns all API fetches with Playwright route mocks, so no backend
 * proxy is installed here. This keeps the smoke deterministic and local-only.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3121,
    strictPort: true,
    host: '127.0.0.1',
  },
  appType: 'spa',
});
