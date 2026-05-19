/**
 * E2E: MCP Installer Wizard — Happy Path (S4d / plan 2026-05-20).
 *
 * Verifies the full local-install flow against the vision-auxiliary
 * dogfood package shape (without actually starting any MCP process —
 * scan + install endpoints are mocked).
 *
 * Flow:
 *   推荐 tab → 视觉辅助 → 选择本地包并安装 → wizard opens
 *   → scan (mocked HIGH-confidence single candidate) → config (skipped, has defaults)
 *   → credentials (CredentialPicker picks the mocked siliconflow cred)
 *   → review → check trust → 安装 → done
 */
import { test, expect } from '@playwright/test';
import { installE2eApiMocks } from './mockApi';

const VISION_PKG_PATH =
  'workspace_references/vision_auxiliary/lit_mcp_vision_auxiliary_pkg';

test.describe('MCP Installer · happy path', () => {
  test.beforeEach(async ({ page }) => {
    await installE2eApiMocks(page);

    // Mock credentials list — one siliconflow credential matches the
    // vision-auxiliary provider_hints.
    await page.route('**/api/credentials**', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              credential_id: 'cred_test_siliconflow',
              category: 'generation',
              provider: 'siliconflow',
              model: 'Qwen2-VL-7B-Instruct',
              base_url: 'https://api.siliconflow.cn/v1',
              protocol: 'openai_chat_completions',
              enabled: true,
              priority: 100,
              tags: [],
              strategy_hint: 'default',
              trust_source: 'runtime_user_confirmed',
              notes: '',
              api_key_masked: 'sk-t...test',
              has_api_key: true,
              fingerprint: 'fp_test',
              fingerprint_version: 'v1',
              created_at: '2026-05-20T00:00:00+00:00',
              updated_at: '2026-05-20T00:00:00+00:00',
            },
          ]),
        });
        return;
      }
      route.continue();
    });

    // Mock list of installed MCP servers — initially empty, then 1 after install.
    let installCount = 0;
    await page.route('**/api/mcp/servers**', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(
            installCount === 0
              ? []
              : [{
                  server_id: 'mcp_test_123',
                  name: '视觉辅助',
                  server_slug: 'vision_auxiliary',
                  transport: 'stdio',
                  stdio: {
                    command: 'python',
                    args: ['-m', 'lit_mcp_vision_auxiliary.server'],
                    env: {},
                    env_refs: { VISION_API_KEY: 'cred_test_siliconflow' },
                    cwd_relative: null,
                  },
                  http: null,
                  provenance: 'runtime_user_confirmed',
                  tags: [],
                  notes: '',
                  approval_state: 'enabled_for_session',
                  fingerprint: 'fp_test',
                  fingerprint_version: 'v2',
                  created_at: '2026-05-20T00:00:00+00:00',
                  updated_at: '2026-05-20T00:00:00+00:00',
                }],
          ),
        });
        return;
      }
      route.continue();
    });

    // Scan endpoint — return HIGH-confidence single-candidate result.
    await page.route('**/api/mcp/installations/scan', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          scan_id: 'scan_test_aaa',
          source_path: VISION_PKG_PATH,
          package_id: 'lit-mcp-vision-auxiliary',
          display_name: '视觉辅助',
          description: 'dogfood package',
          version: '0.1.0',
          confidence: 'high',
          transport: 'stdio',
          launch_candidates: [{
            command: 'python',
            args: ['-m', 'lit_mcp_vision_auxiliary.server'],
            cwd: '.',
            confidence: 'high',
            source: 'literature-mcp.json',
            sha: 'sha_test_001',
          }],
          config_fields: [{
            id: 'vision_provider',
            label: '视觉模型提供方',
            env: 'VISION_PROVIDER',
            type: 'select',
            required: true,
            default: 'siliconflow',
            options: [
              { value: 'siliconflow', label: '硅基流动' },
              { value: 'openai', label: 'OpenAI' },
            ],
            description: '',
          }],
          required_credentials: [{
            id: 'vision_api_key',
            label: '视觉模型 API Key',
            env: 'VISION_API_KEY',
            kind: 'api_key',
            provider_hints: ['siliconflow', 'openai'],
            required: true,
            description: '',
          }],
          expected_tools: ['vision.describe_image', 'vision.extract_text'],
          capabilities: ['read'],
          warnings: [],
          needs_manual_launch: false,
          expires_at: '2099-01-01T00:00:00+00:00',
        }),
      });
    });

    // Install endpoint — success.
    await page.route('**/api/mcp/installations/install', (route) => {
      installCount += 1;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          install_id: 'install_test_zzz',
          server_id: 'mcp_test_123',
          server: {
            server_id: 'mcp_test_123',
            name: '视觉辅助',
            server_slug: 'vision_auxiliary',
            transport: 'stdio',
            stdio: {
              command: 'python',
              args: ['-m', 'lit_mcp_vision_auxiliary.server'],
              env: {},
              env_refs: { VISION_API_KEY: 'cred_test_siliconflow' },
              cwd_relative: null,
            },
            http: null,
            provenance: 'runtime_user_confirmed',
            tags: [],
            notes: '',
            approval_state: 'enabled_for_session',
            fingerprint: 'fp_test',
            fingerprint_version: 'v2',
            created_at: '2026-05-20T00:00:00+00:00',
            updated_at: '2026-05-20T00:00:00+00:00',
          },
          install_dir: '/tmp/mcp_installs/install_test_zzz',
          absolute_cwd: '/tmp/vision-aux-pkg',
          approval_state: 'enabled_for_session',
          probe: {
            status: 'ok',
            tool_count: 2,
            tools: [
              { name: 'vision.describe_image' },
              { name: 'vision.extract_text' },
            ],
            reason: '',
          },
        }),
      });
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.goto('/settings?section=mcp', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('MCP 服务器').first()).toBeVisible({ timeout: 20_000 });
  });

  test('install vision-auxiliary end to end', async ({ page }) => {
    // Recommended tab is default-active.
    await page.getByRole('button', { name: /选择本地包并安装/ }).first().click();

    // Wizard opens at 'source' step.
    await expect(page.getByText('安装 MCP 服务器')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('本地路径')).toBeVisible();

    // Path is preset from the recommended hint — click 扫描.
    await page.getByRole('button', { name: /^扫描/ }).click();

    // Single candidate → skip CandidateStep; land directly on ConfigStep
    // (manifest default fills VISION_PROVIDER=siliconflow), then 下一步 to credentials.
    await expect(page.getByText('视觉模型提供方')).toBeVisible({ timeout: 5_000 });
    await page.getByRole('button', { name: /下一步/ }).click();

    // CredentialPicker shows the mocked siliconflow cred under "匹配 provider".
    await expect(page.getByText('匹配 provider')).toBeVisible({ timeout: 5_000 });
    await page.getByRole('button', { name: /siliconflow/ }).first().click();
    await page.getByRole('button', { name: /下一步/ }).click();

    // Review step — trust checkbox required.
    await expect(page.getByText('我信任此包')).toBeVisible({ timeout: 5_000 });
    await page.getByRole('checkbox', { name: /我信任此包/ }).check();
    await page.getByRole('button', { name: /^安装/ }).click();

    // Done step.
    await expect(page.getByText('安装完成')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/server_id: mcp_test_123/)).toBeVisible();
    await expect(page.getByText('vision.describe_image')).toBeVisible();
    await page.getByRole('button', { name: '完成' }).click();
  });
});
