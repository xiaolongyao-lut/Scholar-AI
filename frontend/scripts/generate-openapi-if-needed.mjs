import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const frontendRoot = path.resolve(path.dirname(__filename), '..');
const repoRoot = path.resolve(frontendRoot, '..');
const schemaPath = path.resolve(frontendRoot, 'openapi', 'modular-pipeline-openapi.json');
const typesPath = path.resolve(frontendRoot, 'src', 'generated', 'openapi.ts');
const backendRoots = [
  path.resolve(repoRoot, 'literature_assistant', 'core', 'python_adapter_server.py'),
  path.resolve(repoRoot, 'literature_assistant', 'core', 'routers'),
  path.resolve(repoRoot, 'literature_assistant', 'core', 'models'),
];

function latestMtimeMs(targetPath) {
  if (!fs.existsSync(targetPath)) return 0;
  const stat = fs.statSync(targetPath);
  if (!stat.isDirectory()) return stat.mtimeMs;
  let latest = stat.mtimeMs;
  for (const entry of fs.readdirSync(targetPath, { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue;
    const child = path.join(targetPath, entry.name);
    if (entry.isDirectory()) {
      latest = Math.max(latest, latestMtimeMs(child));
    } else if (entry.isFile() && entry.name.endsWith('.py')) {
      latest = Math.max(latest, fs.statSync(child).mtimeMs);
    }
  }
  return latest;
}

function isOpenApiCurrent() {
  if (!fs.existsSync(schemaPath) || !fs.existsSync(typesPath)) return false;
  const generatedAt = Math.min(
    fs.statSync(schemaPath).mtimeMs,
    fs.statSync(typesPath).mtimeMs,
  );
  return Math.max(...backendRoots.map(latestMtimeMs)) <= generatedAt;
}

if (!isOpenApiCurrent()) {
  const npmCli = process.env.npm_execpath;
  const command = npmCli ? process.execPath : (process.platform === 'win32' ? 'npm.cmd' : 'npm');
  const args = npmCli ? [npmCli, 'run', 'generate:openapi'] : ['run', 'generate:openapi'];
  const result = spawnSync(command, args, {
    cwd: frontendRoot,
    stdio: 'inherit',
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
