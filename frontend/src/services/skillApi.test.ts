import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SkillApiError, getSkillSecurity, importSkill, validateImportSourcePath } from '@/services/skillApi';

describe('skillApi import validation', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('accepts directory-like local paths', () => {
    expect(validateImportSourcePath('C:\\skills\\my-skill')).toEqual({
      ok: true,
      normalizedPath: 'C:\\skills\\my-skill',
    });
  });

  it('accepts zip packages', () => {
    expect(validateImportSourcePath('C:\\skills\\my-skill.zip')).toEqual({
      ok: true,
      normalizedPath: 'C:\\skills\\my-skill.zip',
    });
  });

  it('rejects unsupported archive suffixes before calling the backend', async () => {
    await expect(importSkill('C:\\skills\\my-skill.rar')).rejects.toMatchObject({
      name: 'SkillApiError',
      status: 400,
      errorCode: 'UNSUPPORTED_SOURCE_PATH',
    });
  });
});

describe('skillApi error parsing', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('preserves structured backend error codes and messages', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
      json: async () => ({
        detail: {
          error_code: 'INVALID_ZIP_ARCHIVE',
          errors: ['Source file is not a valid zip archive: C:\\skills\\bad.zip'],
        },
      }),
    } satisfies Partial<Response>);

    vi.stubGlobal('fetch', fetchMock);

    await expect(importSkill('C:\\skills\\bad.zip')).rejects.toSatisfy((error: unknown) => {
      expect(error).toBeInstanceOf(SkillApiError);
      const typedError = error as SkillApiError;
      expect(typedError.status).toBe(422);
      expect(typedError.errorCode).toBe('INVALID_ZIP_ARCHIVE');
      expect(typedError.errors).toEqual(['Source file is not a valid zip archive: C:\\skills\\bad.zip']);
      expect(typedError.message).toBe('Source file is not a valid zip archive: C:\\skills\\bad.zip');
      return true;
    });
  });
});

describe('skillApi security policy', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('loads machine-readable skill security assessment', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        skill_id: 'user.prompt.network',
        source: 'imported',
        risk_level: 'high',
        runtime_gate: 'block_high_risk_permission',
        runtime_executable: false,
        enable_requires_approval: true,
        high_risk_flags: ['network'],
        denied_operations: ['network'],
        allowed_operations: ['manifest_inspection', 'approval_request', 'rollback'],
        required_sandbox_controls: ['network_allowlist_with_timeout'],
        approval_reason: 'Enable high-risk user Skill permissions: network',
        block_reason: 'High-risk Skill permissions are blocked by the current runtime',
      }),
    } satisfies Partial<Response>);

    vi.stubGlobal('fetch', fetchMock);

    await expect(getSkillSecurity('user.prompt.network')).resolves.toMatchObject({
      skill_id: 'user.prompt.network',
      risk_level: 'high',
      runtime_gate: 'block_high_risk_permission',
      runtime_executable: false,
      enable_requires_approval: true,
      high_risk_flags: ['network'],
    });
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/skills/user.prompt.network/security'));
  });
});
