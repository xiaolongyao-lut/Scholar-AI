import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';

// 0.1.8.1 port-bridge: the backend (python_adapter_server / start_desktop)
// writes its live port to <repo>/workspace_artifacts/runtime_state/api-port.json
// on startup. The proxy router below reads this file *on every request*, so
// the dev frontend follows whatever port uvicorn actually bound to — including
// `--port 8999` or a free-port fallback after 8000 was taken — without anyone
// having to edit this file and without needing to restart vite when the
// backend is restarted on a different port.
const PORT_FILE = path.resolve(
  __dirname, '..', 'workspace_artifacts', 'runtime_state', 'api-port.json',
);
const FALLBACK_TARGET = 'http://127.0.0.1:8000';

function readBackendTarget(): string {
  try {
    if (!fs.existsSync(PORT_FILE)) return FALLBACK_TARGET;
    const raw = fs.readFileSync(PORT_FILE, 'utf-8');
    const data = JSON.parse(raw) as { port?: number };
    if (typeof data.port === 'number' && data.port > 0 && data.port < 65536) {
      return `http://127.0.0.1:${data.port}`;
    }
  } catch {
    /* malformed or unreadable — fall through to default */
  }
  return FALLBACK_TARGET;
}

const initialTarget = readBackendTarget();
if (initialTarget !== FALLBACK_TARGET) {
  // eslint-disable-next-line no-console
  console.log(`[vite] backend proxy → ${initialTarget} (from api-port.json)`);
} else {
  // eslint-disable-next-line no-console
  console.log(
    `[vite] backend proxy → ${FALLBACK_TARGET} (no api-port.json yet; ` +
    `will retry per-request once the backend starts)`,
  );
}

// Per-request override so a backend restart on a different port doesn't
// require restarting vite. Returning a full URL from `router` swaps the
// target for that request. (http-proxy-middleware option.)
function liveBackendRouter(): string {
  return readBackendTarget();
}

const apiTarget = initialTarget;

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
    // Default 3000, but users can override via env (VITE_DEV_PORT=3500
    // npm run dev) or CLI (npm run dev -- --port 3500). We do NOT use
    // strictPort: when 3000 is taken vite falls through to 3001/3002 and
    // prints the chosen port; the proxy stays correct because the
    // backend port is read from api-port.json per-request below.
    port: Number(process.env.VITE_DEV_PORT) || 3000,
    proxy: {
      // True backend API namespaces — proxied unconditionally. Per-request
      // `router` lets the target follow the backend across restarts without
      // restarting vite.
      '/actions': { target: apiTarget, router: liveBackendRouter },
      '/capabilities': { target: apiTarget, router: liveBackendRouter },
      '/health': { target: apiTarget, router: liveBackendRouter },
      '/runtime': { target: apiTarget, router: liveBackendRouter },
      '/resources': { target: apiTarget, router: liveBackendRouter },
      '/skills': { target: apiTarget, router: liveBackendRouter },
      '/pipeline': { target: apiTarget, router: liveBackendRouter },
      '/memory': { target: apiTarget, router: liveBackendRouter },
      '/recovery': { target: apiTarget, router: liveBackendRouter },
      '/autopilot': { target: apiTarget, router: liveBackendRouter },
      '/agent': { target: apiTarget, router: liveBackendRouter },
      '/api': { target: apiTarget, router: liveBackendRouter },
      '/volumes': { target: apiTarget, router: liveBackendRouter },
      // /chat and /inspiration also expose backend subpaths (e.g.
      // /chat/ask, /inspiration/generate). React Router owns the bare
      // /chat and /inspiration paths. `bypass` returns the original
      // path for browser navigation (HTML / Accept: text/html) so the
      // SPA fall-through (Vite default) serves index.html instead of
      // proxying. Subpath API calls fall through to the proxy.
      // Ref: https://vite.dev/config/server-options.html#server-proxy
      '/chat': {
        target: apiTarget,
        router: liveBackendRouter,
        bypass: (req) => {
          const accept = String(req.headers?.accept ?? '');
          if (accept.includes('text/html')) return req.url;
        },
      },
      '/inspiration': {
        target: apiTarget,
        router: liveBackendRouter,
        bypass: (req) => {
          const accept = String(req.headers?.accept ?? '');
          if (accept.includes('text/html')) return req.url;
        },
      },
      // /evolution exposes both bare browser navigation (/evolution → SPA)
      // and backend subpaths (/evolution/status, /evolution/candidates).
      // Same bypass pattern as /chat and /inspiration.
      '/evolution': {
        target: apiTarget,
        router: liveBackendRouter,
        bypass: (req) => {
          const accept = String(req.headers?.accept ?? '');
          if (accept.includes('text/html')) return req.url;
        },
      },
    },
  },
});
