import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';
import { spawnSync } from 'child_process';

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
const CAPABILITY_FILE = path.resolve(
  __dirname, '..', 'workspace_artifacts', 'runtime_state', 'api-capability.json',
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
  console.info(`[vite] backend proxy → ${initialTarget} (from api-port.json)`);
} else {
  console.info(
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

function readCapabilityHeader(): Record<string, string> {
  try {
    if (!fs.existsSync(CAPABILITY_FILE)) return {};
    const raw = fs.readFileSync(CAPABILITY_FILE, 'utf-8');
    const data = JSON.parse(raw) as { header?: unknown; token?: unknown };
    if (typeof data.header === 'string' && data.header.trim() && typeof data.token === 'string' && data.token.trim()) {
      return { [data.header.trim()]: data.token.trim() };
    }
  } catch {
    /* malformed or unreadable — request will be rejected by backend */
  }
  return {};
}

function injectCapabilityHeader(proxyReq: { setHeader: (name: string, value: string) => void }): void {
  const headers = readCapabilityHeader();
  for (const [name, value] of Object.entries(headers)) {
    proxyReq.setHeader(name, value);
  }
}

const withCapability = {
  target: apiTarget,
  router: liveBackendRouter,
  configure: (proxy: { on: (event: 'proxyReq', handler: (proxyReq: { setHeader: (name: string, value: string) => void }) => void) => void }) => {
    proxy.on('proxyReq', injectCapabilityHeader);
  },
};

function normalizeModuleId(id: string): string {
  return id.replace(/\\/g, '/');
}

function manualChunks(id: string): string | undefined {
  const moduleId = normalizeModuleId(id);
  if (
    moduleId.includes('/node_modules/react-pdf/')
    || moduleId.includes('/node_modules/pdfjs-dist/')
  ) {
    return 'pdf-viewer-vendor';
  }
  return undefined;
}

function latestPythonMtimeMs(targetPath: string): number {
  if (!fs.existsSync(targetPath)) return 0;
  const stat = fs.statSync(targetPath);
  if (!stat.isDirectory()) return stat.mtimeMs;
  let latest = stat.mtimeMs;
  for (const entry of fs.readdirSync(targetPath, { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue;
    const childPath = path.join(targetPath, entry.name);
    if (entry.isDirectory()) {
      latest = Math.max(latest, latestPythonMtimeMs(childPath));
    } else if (entry.isFile() && entry.name.endsWith('.py')) {
      latest = Math.max(latest, fs.statSync(childPath).mtimeMs);
    }
  }
  return latest;
}

function openApiIsCurrent(): boolean {
  const schemaPath = path.resolve(__dirname, 'openapi', 'modular-pipeline-openapi.json');
  const typesPath = path.resolve(__dirname, 'src', 'generated', 'openapi.ts');
  if (!fs.existsSync(schemaPath) || !fs.existsSync(typesPath)) return false;
  const generatedAt = Math.min(
    fs.statSync(schemaPath).mtimeMs,
    fs.statSync(typesPath).mtimeMs,
  );
  const backendRoots = [
    path.resolve(__dirname, '..', 'literature_assistant', 'core', 'python_adapter_server.py'),
    path.resolve(__dirname, '..', 'literature_assistant', 'core', 'routers'),
    path.resolve(__dirname, '..', 'literature_assistant', 'core', 'models'),
  ];
  return Math.max(...backendRoots.map(latestPythonMtimeMs)) <= generatedAt;
}

function autoGenerateOpenApiPlugin() {
  return {
    name: 'litassist-openapi-sync',
    buildStart(): void {
      if (openApiIsCurrent()) return;
      const npmCli = process.env.npm_execpath;
      const command = npmCli ? process.execPath : (process.platform === 'win32' ? 'npm.cmd' : 'npm');
      const args = npmCli ? [npmCli, 'run', 'generate:openapi'] : ['run', 'generate:openapi'];
      const result = spawnSync(command, args, {
        cwd: __dirname,
        stdio: 'inherit',
      });
      if (result.status !== 0) {
        throw new Error(`OpenAPI generation failed with exit code ${result.status ?? 1}`);
      }
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), autoGenerateOpenApiPlugin()],
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
  build: {
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
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
      '/actions': withCapability,
      '/capabilities': withCapability,
      '/health': { target: apiTarget, router: liveBackendRouter },
      '/runtime': withCapability,
      '/resources': withCapability,
      '/skills': withCapability,
      '/skill_packs': withCapability,
      '/pipeline': withCapability,
      '/memory': withCapability,
      '/recovery': withCapability,
      '/autopilot': withCapability,
      '/agent/': withCapability,
      '/api': withCapability,
      '/volumes': withCapability,
      '/sampling': withCapability,
      '/run_action': withCapability,
      '/transform_result': withCapability,
      // /chat and /inspiration also expose backend subpaths (e.g.
      // /chat/ask, /inspiration/generate). React Router owns the bare
      // /chat and /inspiration paths. `bypass` returns the original
      // path for browser navigation (HTML / Accept: text/html) so the
      // SPA fall-through (Vite default) serves index.html instead of
      // proxying. Subpath API calls fall through to the proxy.
      // Ref: https://vite.dev/config/server-options.html#server-proxy
      '/chat': {
        ...withCapability,
        bypass: (req) => {
          const accept = String(req.headers?.accept ?? '');
          if (accept.includes('text/html')) return req.url;
        },
      },
      '/inspiration': {
        ...withCapability,
        bypass: (req) => {
          const accept = String(req.headers?.accept ?? '');
          if (accept.includes('text/html')) return req.url;
        },
      },
      // /evolution exposes both bare browser navigation (/evolution → SPA)
      // and backend subpaths (/evolution/status, /evolution/candidates).
      // Same bypass pattern as /chat and /inspiration.
      '/evolution': {
        ...withCapability,
        bypass: (req) => {
          const accept = String(req.headers?.accept ?? '');
          if (accept.includes('text/html')) return req.url;
        },
      },
    },
  },
});
