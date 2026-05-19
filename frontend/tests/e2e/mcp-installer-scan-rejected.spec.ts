/**
 * E2E: MCP Installer Wizard — scan_rejected on remote URL (S4d).
 *
 * Verifies that the scanner's safety boundary surfaces in the UI:
 * remote URLs in source_path are rejected by the backend with
 * detail.code=scan_rejected; the wizard renders the ErrorStep.
 */
import { test, expect } from '@playwright/test';
import { installE2eApiMocks } from './mockApi';

test.describe('MCP Installer · scan_rejected (remote URL)', () => {
  test.beforeEach(async ({ page }) => {
    await installE2eApiMocks(page);
    await page.route('**/api/credentials**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    );
    await page.route('**/api/mcp/servers**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    );

    // Scan rejects with 400 scan_rejected — matches backend mcp_installer_router
    // McpPackageScanError mapping.
    await page.route('**/api/mcp/installations/scan', (route) => {
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: {
            code: 'scan_rejected',
            message: 'remote URLs are not allowed as source_path: \'https://evil.example.com/mcp.zip\'',
          },
        }),
      });
    });

    await page.goto('/settings?section=mcp', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('MCP 服务器').first()).toBeVisible({ timeout: 20_000 });
  });

  test('rejects remote URL with scan_rejected error', async ({ page }) => {
    // Switch to 本地安装 tab.
    await page.getByRole('tab', { name: /本地安装/ }).click();

    // Type remote URL into the path input and start scan.
    await page.getByPlaceholder(/\/path\/to\/my-mcp-package/).fill('https://evil.example.com/mcp.zip');
    await page.getByRole('button', { name: /开始扫描/ }).click();

    // Wizard opens, immediately runs scan (since path preset triggers the
    // user clicking the "扫描" button manually).
    await page.getByRole('button', { name: /^扫描/ }).click();

    // ErrorStep shows.
    await expect(page.getByText('安装失败')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('scan_rejected')).toBeVisible();
    await expect(page.getByText(/remote URLs are not allowed/)).toBeVisible();
  });
});
