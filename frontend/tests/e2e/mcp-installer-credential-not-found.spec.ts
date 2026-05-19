/**
 * E2E: MCP Installer Wizard — install fails with credential_not_found (S4d).
 *
 * Reproduces the case where a stale binding (or the user editing the cred
 * outside the wizard) leaves a credential_id that no longer resolves.
 * The wizard surfaces the ErrorStep with the code and offers Retry / 修复配置.
 */
import { test, expect } from '@playwright/test';
import { installE2eApiMocks } from './mockApi';

test.describe('MCP Installer · credential_not_found on install', () => {
  test.beforeEach(async ({ page }) => {
    await installE2eApiMocks(page);

    await page.route('**/api/credentials**', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              credential_id: 'cred_stale_xxx',
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
              api_key_masked: 'sk-s...stal',
              has_api_key: true,
              fingerprint: 'fp_stale',
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

    await page.route('**/api/mcp/servers**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    );

    await page.route('**/api/mcp/installations/scan', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          scan_id: 'scan_stale_yyy',
          source_path: 'workspace_references/vision_auxiliary/lit_mcp_vision_auxiliary_pkg',
          package_id: 'lit-mcp-vision-auxiliary',
          display_name: '视觉辅助',
          description: '',
          version: '0.1.0',
          confidence: 'high',
          transport: 'stdio',
          launch_candidates: [{
            command: 'python',
            args: ['-m', 'lit_mcp_vision_auxiliary.server'],
            cwd: '.',
            confidence: 'high',
            source: 'literature-mcp.json',
            sha: 'sha_stale_001',
          }],
          config_fields: [],
          required_credentials: [{
            id: 'vision_api_key',
            label: '视觉模型 API Key',
            env: 'VISION_API_KEY',
            kind: 'api_key',
            provider_hints: ['siliconflow'],
            required: true,
            description: '',
          }],
          expected_tools: [],
          capabilities: [],
          warnings: [],
          needs_manual_launch: false,
          expires_at: '2099-01-01T00:00:00+00:00',
        }),
      }),
    );

    // Install returns 400 credential_not_found.
    await page.route('**/api/mcp/installations/install', (route) =>
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: {
            code: 'credential_not_found',
            message:
              "credential binding for 'VISION_API_KEY' references unknown credential_id 'cred_stale_xxx'",
          },
        }),
      }),
    );

    await page.goto('/settings?section=mcp', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('MCP 服务器').first()).toBeVisible({ timeout: 20_000 });
  });

  test('install error surfaces credential_not_found with retry + fix-config', async ({ page }) => {
    await page.getByRole('button', { name: /选择本地包并安装/ }).first().click();
    await page.getByRole('button', { name: /^扫描/ }).click();

    // No config_fields in this fixture → wizard lands on CredentialsStep.
    await expect(page.getByText('匹配 provider')).toBeVisible({ timeout: 5_000 });
    await page.getByRole('button', { name: /siliconflow/ }).first().click();
    await page.getByRole('button', { name: /下一步/ }).click();

    // Review with trust + install → backend returns credential_not_found.
    await page.getByRole('checkbox', { name: /我信任此包/ }).check();
    await page.getByRole('button', { name: /^安装/ }).click();

    await expect(page.getByText('安装失败')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('credential_not_found')).toBeVisible();
    // Retry + Fix buttons exposed
    await expect(page.getByRole('button', { name: /重试/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /修复配置/ })).toBeVisible();
  });
});
