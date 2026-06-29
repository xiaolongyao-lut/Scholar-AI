import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const frontendRoot = path.resolve(path.dirname(__filename), '..');
const repoRoot = path.resolve(frontendRoot, '..');
const defaultOutput = path.resolve(frontendRoot, 'openapi', 'modular-pipeline-openapi.json');

function candidatePythonExecutables() {
  const explicit = process.env.LITASSIST_PYTHON || process.env.PYTHON;
  const candidates = [
    explicit,
    process.platform === 'win32'
      ? path.resolve(repoRoot, '.venv-1', 'Scripts', 'python.exe')
      : path.resolve(repoRoot, '.venv-1', 'bin', 'python'),
    'python',
    process.platform === 'win32' ? undefined : 'python3',
  ];
  return candidates.filter((value) => typeof value === 'string' && value.trim().length > 0);
}

function commandExists(command) {
  if (path.isAbsolute(command) || command.includes(path.sep)) {
    return fs.existsSync(command);
  }
  const probe = spawnSync(command, ['--version'], { stdio: 'ignore' });
  return probe.error === undefined && probe.status === 0;
}

function resolvePythonExecutable() {
  for (const command of candidatePythonExecutables()) {
    if (commandExists(command)) return command;
  }
  throw new Error('No Python executable found. Set LITASSIST_PYTHON to a valid interpreter.');
}

const outputArgIndex = process.argv.indexOf('--output');
const outputPath = outputArgIndex >= 0 && process.argv[outputArgIndex + 1]
  ? path.resolve(frontendRoot, process.argv[outputArgIndex + 1])
  : defaultOutput;
const python = resolvePythonExecutable();
const result = spawnSync(
  python,
  [
    path.resolve(repoRoot, 'scripts', 'export_openapi_schema.py'),
    '--output',
    outputPath,
  ],
  {
    cwd: repoRoot,
    stdio: 'inherit',
  },
);

if (result.error) {
  throw result.error;
}
process.exit(result.status ?? 1);
