/**
 * Skill management API service.
 *
 * Consumes the backend /skills/* endpoints for user skill CRUD.
 */
import type {
  SkillDescriptor,
  ImportResult,
  SkillAuditEvent,
  SkillEnableResult,
  SkillTestRunResult,
  SkillApprovalDecision,
  SkillApprovalDecisionResult,
  SkillApprovalRequest,
  SkillRollbackResult,
  SkillSecurityAssessment,
  SkillUninstallResult,
  SkillExportResult,
  SkillRuntimeSettings,
} from '@/types/skills';
import { getApiBaseUrl } from './apiBaseUrl';

const BASE = getApiBaseUrl();

export type SkillImportErrorCode =
  | 'EMPTY_SOURCE_PATH'
  | 'UNSUPPORTED_SOURCE_PATH'
  | 'SOURCE_PATH_NOT_FOUND'
  | 'INVALID_ZIP_ARCHIVE'
  | 'UNSAFE_ARCHIVE_ENTRY'
  | 'INVALID_MANIFEST'
  | 'MISSING_SKILL_MD'
  | 'PACKAGE_LIMIT_EXCEEDED'
  | 'IMPORT_VALIDATION_FAILED'
  | 'INVALID_SOURCE_PATH';

interface SkillApiProblemDetailPayload {
  error_code?: string;
  errors?: string[];
}

interface SkillImportPathValidationResult {
  ok: boolean;
  normalizedPath: string;
  errorCode?: SkillImportErrorCode;
  message?: string;
}

const UNSUPPORTED_IMPORT_FILE_SUFFIXES = [
  '.7z',
  '.bz2',
  '.doc',
  '.docx',
  '.gz',
  '.json',
  '.md',
  '.pdf',
  '.rar',
  '.tar',
  '.tgz',
  '.txt',
  '.xz',
] as const;

export class SkillApiError extends Error {
  /** HTTP status carried by backend skill APIs for UI-specific recovery paths. */
  readonly status: number;
  readonly errorCode?: string;
  readonly errors: string[];

  constructor(message: string, status: number, errorCode?: string, errors: string[] = []) {
    super(message);
    this.name = 'SkillApiError';
    this.status = status;
    this.errorCode = errorCode;
    this.errors = errors;
  }
}

function isProblemDetailPayload(value: unknown): value is SkillApiProblemDetailPayload {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseErrorPayload(payload: unknown, fallbackMessage: string): { message: string; errorCode?: string; errors: string[] } {
  if (
    typeof payload === 'object' &&
    payload !== null &&
    'detail' in payload
  ) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string') {
      return { message: detail, errors: [detail] };
    }
    if (isProblemDetailPayload(detail)) {
      const errors = Array.isArray(detail.errors)
        ? detail.errors.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
        : [];
      const message = errors[0] ?? fallbackMessage;
      return {
        message,
        errorCode: detail.error_code,
        errors,
      };
    }
  }

  return { message: fallbackMessage, errors: [fallbackMessage] };
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ detail: res.statusText }));
    const parsed = parseErrorPayload(payload, res.statusText);
    throw new SkillApiError(parsed.message, res.status, parsed.errorCode, parsed.errors);
  }
  return res.json();
}

export function validateImportSourcePath(sourcePath: string): SkillImportPathValidationResult {
  const normalizedPath = sourcePath.trim();
  if (normalizedPath.length === 0) {
    return {
      ok: false,
      normalizedPath,
      errorCode: 'EMPTY_SOURCE_PATH',
      message: 'Import source path is required',
    };
  }

  if (/^[a-z]+:\/\//i.test(normalizedPath)) {
    return {
      ok: false,
      normalizedPath,
      errorCode: 'UNSUPPORTED_SOURCE_PATH',
      message: 'Only local directories or .zip packages are supported',
    };
  }

  const lowered = normalizedPath.toLowerCase();
  if (lowered.endsWith('.zip')) {
    return { ok: true, normalizedPath };
  }

  if (UNSUPPORTED_IMPORT_FILE_SUFFIXES.some((suffix) => lowered.endsWith(suffix))) {
    return {
      ok: false,
      normalizedPath,
      errorCode: 'UNSUPPORTED_SOURCE_PATH',
      message: 'Only local directories or .zip packages are supported',
    };
  }

  return { ok: true, normalizedPath };
}

/** List all skills, optionally filtered */
export async function listSkills(params?: {
  ui_mode?: string;
  kind?: string;
  source?: string;
}): Promise<SkillDescriptor[]> {
  const qs = new URLSearchParams();
  if (params?.ui_mode) qs.set('ui_mode', params.ui_mode);
  if (params?.kind) qs.set('kind', params.kind);
  if (params?.source) qs.set('source', params.source);
  const res = await fetch(`${BASE}/skills?${qs}`);
  return handleResponse(res);
}

/** Get a single skill by ID */
export async function getSkill(skillId: string): Promise<SkillDescriptor> {
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}`);
  return handleResponse(res);
}

/** Persist manifest-driven runtime settings for an imported skill */
export async function updateSkillRuntimeSettings(
  skillId: string,
  settings: SkillRuntimeSettings,
): Promise<SkillRuntimeSettings & { skill_id: string }> {
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/runtime-settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  });
  return handleResponse(res);
}

/** Get the current runtime safety policy for one skill */
export async function getSkillSecurity(skillId: string): Promise<SkillSecurityAssessment> {
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/security`);
  return handleResponse(res);
}

/** Import a user skill from a local directory path or zip package */
export async function importSkill(sourcePath: string): Promise<ImportResult> {
  const validation = validateImportSourcePath(sourcePath);
  if (!validation.ok) {
    throw new SkillApiError(
      validation.message ?? 'Invalid import source path',
      400,
      validation.errorCode,
      validation.message ? [validation.message] : [],
    );
  }
  const res = await fetch(`${BASE}/skills/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_path: validation.normalizedPath }),
  });
  return handleResponse(res);
}

/** Enable a skill */
export async function enableSkill(skillId: string): Promise<SkillEnableResult> {
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/enable`, { method: 'POST' });
  return handleResponse(res);
}

/** Disable a skill */
export async function disableSkill(skillId: string, reason?: string): Promise<SkillEnableResult> {
  const qs = new URLSearchParams();
  if (reason) qs.set('reason', reason);
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/disable?${qs}`, { method: 'POST' });
  return handleResponse(res);
}

/** Test-run a skill with sample input */
export async function testRunSkill(skillId: string, inputText?: string): Promise<SkillTestRunResult> {
  const qs = new URLSearchParams();
  if (inputText) qs.set('input_text', inputText);
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/test-run?${qs}`, { method: 'POST' });
  return handleResponse(res);
}

/** Get audit events */
export async function getSkillAudit(skillId?: string, limit?: number): Promise<SkillAuditEvent[]> {
  const qs = new URLSearchParams();
  if (skillId) qs.set('skill_id', skillId);
  if (limit) qs.set('limit', String(limit));
  const res = await fetch(`${BASE}/skills/audit?${qs}`);
  return handleResponse(res);
}

/** List approval requests still waiting for a final decision */
export async function listPendingApprovals(): Promise<SkillApprovalRequest[]> {
  const res = await fetch(`${BASE}/skills/approvals/pending`);
  return handleResponse(res);
}

/** Record a decision for a pending approval request */
export async function decideApproval(
  requestId: string,
  decision: SkillApprovalDecision,
  reason?: string,
): Promise<SkillApprovalDecisionResult> {
  const res = await fetch(`${BASE}/skills/approvals/${encodeURIComponent(requestId)}/decide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, reason }),
  });
  return handleResponse(res);
}

/** Preview or execute uninstall for a managed user skill */
export async function uninstallSkill(skillId: string, options?: { dryRun?: boolean }): Promise<SkillUninstallResult> {
  const qs = new URLSearchParams();
  if (options?.dryRun) qs.set('dry_run', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}${suffix}`, { method: 'DELETE' });
  return handleResponse(res);
}

/** Restore a managed user skill from the latest or explicit rollback snapshot */
export async function rollbackSkill(skillId: string, backupPath?: string): Promise<SkillRollbackResult> {
  const body = backupPath && backupPath.trim().length > 0 ? { backup_path: backupPath.trim() } : {};
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/rollback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

/** Export a managed user skill to a backend-local zip archive. */
export async function exportSkill(skillId: string, outputPath?: string): Promise<SkillExportResult> {
  const qs = new URLSearchParams();
  if (outputPath && outputPath.trim().length > 0) {
    qs.set('output_path', outputPath.trim());
  }
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/export${suffix}`, { method: 'POST' });
  return handleResponse(res);
}
