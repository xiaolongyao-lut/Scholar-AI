import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      // Legacy frontend snapshot (Slice 0): read-only reference, must
      // NOT be discovered by the active vitest run.
      '../workspace_references/**',
      '**/workspace_references/**',
    ],
    setupFiles: ['./src/test/setup.ts'],
  },
  server: {
    port: 3000,
    proxy: {
      // True backend API namespaces — proxied unconditionally.
      '/actions': 'http://127.0.0.1:8000',
      '/capabilities': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/runtime': 'http://127.0.0.1:8000',
      '/resources': 'http://127.0.0.1:8000',
      '/skills': 'http://127.0.0.1:8000',
      '/pipeline': 'http://127.0.0.1:8000',
      '/memory': 'http://127.0.0.1:8000',
      '/recovery': 'http://127.0.0.1:8000',
      '/autopilot': 'http://127.0.0.1:8000',
      '/agent': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:8000',
      '/volumes': 'http://127.0.0.1:8000',
      // /chat and /inspiration also expose backend subpaths (e.g.
      // /chat/ask, /inspiration/generate). React Router owns the bare
      // /chat and /inspiration paths. `bypass` returns the original
      // path for browser navigation (HTML / Accept: text/html) so the
      // SPA fall-through (Vite default) serves index.html instead of
      // proxying. Subpath API calls fall through to the proxy.
      // Ref: https://vite.dev/config/server-options.html#server-proxy
      '/chat': {
        target: 'http://127.0.0.1:8000',
        bypass: (req) => {
          const accept = String(req.headers?.accept ?? '');
          if (accept.includes('text/html')) return req.url;
        },
      },
      '/inspiration': {
        target: 'http://127.0.0.1:8000',
        bypass: (req) => {
          const accept = String(req.headers?.accept ?? '');
          if (accept.includes('text/html')) return req.url;
        },
      },
      // /evolution exposes both bare browser navigation (/evolution → SPA)
      // and backend subpaths (/evolution/status, /evolution/candidates).
      // Same bypass pattern as /chat and /inspiration.
      '/evolution': {
        target: 'http://127.0.0.1:8000',
        bypass: (req) => {
          const accept = String(req.headers?.accept ?? '');
          if (accept.includes('text/html')) return req.url;
        },
      },
    },
  },
});
