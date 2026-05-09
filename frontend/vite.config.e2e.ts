import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

/**
 * Vite config for E2E tests (TASK-192).
 *
 * Identical to the main vite.config.ts but WITHOUT the server proxy.
 * This ensures API requests from the browser are NOT forwarded to
 * http://127.0.0.1:8000 and can be intercepted by Playwright's
 * page.route() mocks instead.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3100,
    strictPort: true,
    host: '127.0.0.1',
    // NO proxy — all API calls handled by Playwright route mocks
  },
  appType: 'spa',
});
