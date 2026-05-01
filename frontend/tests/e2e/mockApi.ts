import type { Page, Route } from '@playwright/test';
import type {
  SkillApprovalRequest,
  SkillAuditEvent,
  SkillDescriptor,
  SkillSecurityAssessment,
  SkillTestRunResult,
} from '../../src/types/skills';

type JsonValue = boolean | number | string | null | JsonValue[] | { [key: string]: JsonValue };

const json = async (route: Route, body: JsonValue, status = 200): Promise<void> => {
  const resourceType = route.request().resourceType();
  // IMPORTANT: Only intercept API-like requests (fetch/xhr). 
  // Do NOT intercept documents, scripts, or styles which belong to Vite.
  if (resourceType !== 'fetch' && resourceType !== 'xhr') {
    return route.continue();
  }

  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
};

const buildSkill = (overrides: Partial<SkillDescriptor>): SkillDescriptor => ({
  id: 'user.prompt.polish',
  name: '文献润色 Skill',
  description: '将用户选中文本改写为更适合论文语境的表述。',
  kind: 'prompt',
  source: 'imported',
  entry_mode: 'prompt',
  supported_scopes: ['selection', 'section'],
  ui_visibility: 'visible',
  requires_assets: false,
  prompt_template_refs: ['prompt.md'],
  script_refs: [],
  reference_refs: [],
  tags: ['writing', 'rag'],
  version: '1.0.0',
  display_group: '用户 Skill',
  experimental: false,
  safe_to_execute: true,
  capability_refs: ['writing.rewrite'],
  default_parameters: { permissions: { 'draft.read': true, 'draft.write': true, 'references.read': true } },
  import_origin: 'C:\\fake\\path\\to\\skill',
  summary_hint: '论文表达润色',
  compatibility: {
    fallback_action_id: null,
    min_app_version: null,
    max_app_version: null,
  },
  disabled_reason: null,
  script_policy: {
    has_scripts: false,
    safe_to_execute: true,
    disabled_reason: null,
  },
  trust_level: 'limited',
  ...overrides,
});

const enabledUserSkill = buildSkill({});
const disabledUserSkill = buildSkill({ disabled_reason: 'disabled by e2e fixture' });
const builtinSkill = buildSkill({
  id: 'builtin.rag.answer',
  name: 'RAG 回答',
  description: '基于检索证据生成可追溯回答。',
  source: 'builtin',
  display_group: '基础能力',
  import_origin: null,
  trust_level: 'trusted',
  default_parameters: { permissions: { 'model.llm': true, 'retrieval.read': true, 'references.read': true } },
});

const auditEvents: SkillAuditEvent[] = [
  {
    event_id: 'audit-1',
    event_type: 'EXECUTION_COMPLETED',
    timestamp: '2026-04-30T12:00:00Z',
    job_id: 'job-1',
    capability_id: 'user.prompt.polish',
    description: 'Skill test run completed in the E2E fixture.',
    severity: 'info',
    error_message: null,
  },
];

const approvalRequest: SkillApprovalRequest = {
  request_id: 'approval-1',
  capability_id: 'user.prompt.polish',
  capability_name: '文献润色 Skill',
  reason: '该 Skill 请求访问草稿内容以执行润色。',
  timestamp: '2026-04-30T12:00:00Z',
  context: { scope: 'selection' },
};

const highRiskSkill = buildSkill({
  id: 'user.prompt.network',
  name: '联网检索 Skill',
  description: '需要网络权限的高风险用户 Skill。',
  disabled_reason: 'Imported skill - not yet enabled',
  default_parameters: { permissions: { 'draft.read': true, network: true } },
  trust_level: 'untrusted',
});

const highRiskSecurityAssessment: SkillSecurityAssessment = {
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
};

const safeSecurityAssessment: SkillSecurityAssessment = {
  skill_id: 'user.prompt.polish',
  source: 'imported',
  risk_level: 'low',
  runtime_gate: 'allow_controlled_prompt',
  runtime_executable: true,
  enable_requires_approval: false,
  high_risk_flags: [],
  denied_operations: [],
  allowed_operations: ['controlled_prompt_template_render', 'audit_append', 'rollback'],
  required_sandbox_controls: [],
  approval_reason: null,
  block_reason: null,
};

const testRunResult: SkillTestRunResult = {
  job_id: 'job-1',
  skill_id: 'user.prompt.polish',
  status: 'success',
  input_text: 'sample input',
  output_text: '改写后的论文表达。',
  timestamp: '2026-04-30T12:00:00Z',
  execution_time_ms: 42,
  warnings: [],
  metadata: {},
  structured_output: {
    execution_mode: 'prompt',
    skill_id: 'user.prompt.polish',
    skill_kind: 'prompt',
  },
  evidence_refs: [
    {
      chunk_id: 'chunk-1',
      title: 'fixture evidence',
      quote: 'supporting quote',
      score: 0.92,
    },
  ],
  audit_id: 'audit-1',
};

const samplingResponse = {
  defaults_version: 'e2e',
  model_max_tokens: 32768,
  tasks: {},
  task_defaults: {
    chat: { temperature: 0.2, top_p: 0.9, top_k: 40, max_tokens: 2048 },
    writing: { temperature: 0.2, top_p: 0.9, top_k: 40, max_tokens: 4096 },
  },
};

export async function installE2eApiMocks(page: Page): Promise<void> {
  let skillEnabled = true;
  let skillInstalled = true;
  let highRiskEnabled = false;
  let pendingApprovals: SkillApprovalRequest[] = [approvalRequest];

  // Clean state before each test
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  // ----- Core API routes -----
  await page.route('**/health', route => json(route, { status: 'ok', modules: { resources: 'ready', skills: 'ready' } }));
  await page.route('**/chat/providers', route => json(route, [])); // MUST be an array
  await page.route('**/chat/models', route => json(route, []));
  await page.route('**/sampling**', route => json(route, samplingResponse));
  await page.route('**/resources/projects**', route => json(route, []));
  await page.route('**/resources/project/*/stats**', route => json(route, { sections: 0, drafts: 0, materials: 0, revisions: 0 }));
  await page.route('**/resources/documents**', route => json(route, []));
  await page.route('**/resources/chunks**', route => json(route, { chunks: [], results: [] }));
  await page.route('**/resources/sections**', route => json(route, []));
  await page.route('**/resources/materials**', route => json(route, []));
  await page.route('**/resources/drafts**', route => json(route, []));
  await page.route('**/resources/stats/overview**', route => json(route, { projects: 0, materials: 0, drafts: 0 }));
  await page.route('**/volumes**', route => json(route, { total: 0, volumes: [] }));
  await page.route('**/actions**', route => json(route, []));

  // ----- Inspiration -----
  await page.route('**/inspiration/generate', route => json(route, { sparks: [], total: 0 }));
  await page.route('**/inspiration/reload', route => json(route, { ok: true }));

  // ----- Budget / Chat sessions -----
  await page.route('**/api/budget/status', route => json(route, { call_count: 0, call_cap: 100, cost_usd: 0, budget_usd: 10, percent_calls: 0, percent_usd: 0 }));
  await page.route('**/api/chat/sessions**', route => json(route, { sessions: [] }));

  // ----- Runtime / Jobs -----
  await page.route('**/runtime/sessions**', route => json(route, []));
  await page.route('**/runtime/job/**', route => json(route, { job_id: 'mock', status: 'completed' }));

  // ----- Skills -----
  await page.route('**/skills/audit**', route => json(route, auditEvents));
  await page.route('**/skills/approvals/pending', route => json(route, pendingApprovals));
  await page.route('**/skills/approvals/*/decide', route => {
    pendingApprovals = [];
    return json(route, {
      request_id: 'approval-1',
      decision: 'approved',
      user_id: null,
      timestamp: '2026-04-30T12:01:00Z',
      reason: null,
    });
  });
  await page.route('**/skills/import', async route => {
    const body = route.request().postDataJSON() as { source_path?: string } | null;
    const sourcePath = body?.source_path ?? '';
    if (sourcePath.endsWith('invalid-skill.zip')) {
      return json(route, { detail: { error_code: 'INVALID_ZIP_ARCHIVE', errors: ['Invalid zip archive'] } }, 422);
    }
    if (sourcePath.endsWith('valid-skill.zip')) {
      skillInstalled = true;
      return json(route, {
        success: true,
        skill_id: 'user.prompt.polish',
        installed_path: 'C:\\managed\\user.prompt.polish',
        content_hash: 'sha256:e2e',
        origin: sourcePath,
        installed_at: '2026-05-01T03:20:00Z',
        errors: [],
        warnings: [],
        manifest: {
          id: 'user.prompt.polish',
          name: '文献润色 Skill',
          version: '1.0.0',
          kind: 'prompt',
          high_risk_flags: [],
        },
      });
    }
    return json(route, { detail: 'Skill directory does not exist' }, 400);
  });
  await page.route('**/skills/*/test-run**', route => json(route, testRunResult));
  await page.route('**/skills/*/security', route => {
    if (route.request().url().includes('user.prompt.network')) {
      return json(route, highRiskSecurityAssessment as unknown as JsonValue);
    }
    return json(route, safeSecurityAssessment as unknown as JsonValue);
  });
  await page.route('**/skills/*/disable**', route => {
    skillEnabled = false;
    return json(route, { skill_id: 'user.prompt.polish', enabled: false, reason: 'disabled by e2e fixture' });
  });
  await page.route('**/skills/*/enable**', route => {
    if (route.request().url().includes('user.prompt.network')) {
      if (!highRiskEnabled) {
        pendingApprovals = [
          {
            ...approvalRequest,
            request_id: 'approval-high-risk',
            capability_id: 'user.prompt.network',
            capability_name: '联网检索 Skill',
            reason: 'Enable high-risk user skill permissions: network',
          },
        ];
        highRiskEnabled = true;
        return json(route, { detail: 'Approval required before enabling high-risk skill: approval-high-risk' }, 409);
      }
      return json(route, { skill_id: 'user.prompt.network', enabled: true });
    }
    skillEnabled = true;
    return json(route, { skill_id: 'user.prompt.polish', enabled: true });
  });
  await page.route('**/skills/*/rollback', route => {
    skillInstalled = true;
    skillEnabled = true;
    return json(route, {
      skill_id: 'user.prompt.polish',
      rolled_back: true,
      restored_path: 'C:\\managed\\user.prompt.polish',
      backup_path: 'C:\\managed\\.rollback_snapshots\\user.prompt.polish-20260430120000Z',
      warnings: [],
    });
  });
  const uninstallHandler = (route: Route): Promise<void> => {
    if (route.request().method() === 'DELETE') {
      const url = new URL(route.request().url());
      const dryRun = url.searchParams.get('dry_run') === 'true';
      if (!dryRun) {
        skillInstalled = false;
      }
      return json(route, {
        skill_id: 'user.prompt.polish',
        uninstalled: !dryRun,
        dry_run: dryRun,
        backup_path: 'C:\\managed\\.rollback_snapshots\\user.prompt.polish-20260430120000Z',
        removed_path: 'C:\\managed\\user.prompt.polish',
        warnings: [],
      });
    }
    return route.continue();
  };
  await page.route('**/skills/user.prompt.polish?**', uninstallHandler);
  await page.route('**/skills/user.prompt.polish', uninstallHandler);

  const currentSkills = (): JsonValue[] => {
    const skills: JsonValue[] = [];
    if (skillInstalled) {
      skills.push(skillEnabled ? enabledUserSkill as unknown as JsonValue : disabledUserSkill as unknown as JsonValue);
    }
    skills.push(highRiskEnabled ? { ...highRiskSkill, disabled_reason: null } as unknown as JsonValue : highRiskSkill as unknown as JsonValue);
    skills.push(builtinSkill as unknown as JsonValue);
    return skills;
  };
  await page.route('**/skills?**', route => json(route, currentSkills()));
  await page.route('**/skills', route => json(route, currentSkills()));

  // ----- Catch-all for any other API endpoints to prevent network errors -----
  await page.route('**/api/**', route => {
    // Only intercept if not already handled
    if (!route.request().url().includes('/api/budget') && !route.request().url().includes('/api/chat')) {
      return json(route, {});
    }
    return route.continue();
  });
}
