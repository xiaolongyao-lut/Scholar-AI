/**
 * E2E: Skill Manager (TASK-191 / TASK-192)
 *
 * Verifies the Skill Manager lifecycle:
 * 1. Rendering sections (builtin + user).
 * 2. Importing a user skill (error path).
 * 3. Toggling enable/disable.
 * 4. Running a test.
 * 5. Viewing audit log.
 * 6. Approval decision, uninstall, and rollback controls.
 *
 * TASK-192 stability:
 * - Navigates to /settings first, then clicks the Skills tab
 *   (avoids query-string related blank-page issues on Windows).
 * - Uses `domcontentloaded` and generous timeouts.
 */
import { test, expect } from '@playwright/test';
import { installE2eApiMocks } from './mockApi';

test.describe('Skill Manager E2E', () => {
  test.beforeEach(async ({ page }) => {
    await installE2eApiMocks(page);
    
    // Warm up root
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main')).toBeVisible({ timeout: 10_000 });

    // Navigate to plain /settings first
    await page.goto('/settings', { waitUntil: 'domcontentloaded' });
    // Wait for Settings page main content
    await expect(page.locator('main')).toBeVisible({ timeout: 20_000 });
    // Now click the Skills tab to switch sections
    await page.getByRole('button', { name: 'Skill 管理' }).click();
    // Wait for Skill Manager lazy component to load and render
    await expect(page.getByText('导入用户 Skill')).toBeVisible({ timeout: 15_000 });
  });

  test('should render builtin and user skill sections', async ({ page }) => {
    await expect(page.getByText('我的 Skill')).toBeVisible();
    await expect(page.getByText('基础能力')).toBeVisible();
    await expect(page.getByText('文献润色 Skill')).toBeVisible();
    await expect(page.getByText('RAG 回答')).toBeVisible();
  });

  test('should handle skill import attempt', async ({ page }) => {
    const input = page.getByPlaceholder('Skill 目录或 .zip 路径…');
    const importBtn = page.getByRole('button', { name: '导入' });

    await input.fill('C:\\fake\\path\\to\\skill');
    await importBtn.click();

    await expect(page.getByText('Skill directory does not exist')).toBeVisible({ timeout: 10_000 });
  });

  test('should show zip import success with runtime boundary copy', async ({ page }) => {
    await expect(page.getByText('支持文件夹或 .zip 包')).toBeVisible();
    await expect(page.getByText('导入/启用不等于允许脚本或网络执行')).toBeVisible();

    const input = page.getByPlaceholder('Skill 目录或 .zip 路径…');
    await input.fill('C:\\fake\\packages\\valid-skill.zip');
    await page.getByRole('button', { name: '导入' }).click();

    await expect(page.getByText('已导入 Skill：文献润色 Skill')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('来源：C:\\fake\\packages\\valid-skill.zip')).toBeVisible();
    await expect(page.getByText('运行边界：脚本/网络执行仍按安全策略拦截')).toBeVisible();
    await expect(input).toHaveValue('');
  });

  test('should render machine-readable zip validation errors as Chinese guidance', async ({ page }) => {
    const input = page.getByPlaceholder('Skill 目录或 .zip 路径…');
    await input.fill('C:\\fake\\packages\\invalid-skill.zip');
    await page.getByRole('button', { name: '导入' }).click();

    await expect(page.getByText('导入失败：压缩包格式无效或已损坏')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('请重新导出 .zip 包，或先在本地解压检查 skill.json/manifest 文件。')).toBeVisible();
  });

  test('should reject unsupported import file suffix before calling backend', async ({ page }) => {
    const input = page.getByPlaceholder('Skill 目录或 .zip 路径…');
    await input.fill('C:\\fake\\packages\\invalid-skill.rar');
    await page.getByRole('button', { name: '导入' }).click();

    await expect(page.getByText('导入失败：只支持本地目录或 .zip 包')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('请填写后端可访问的本地 Skill 目录，或提供 .zip 包路径。')).toBeVisible();
  });

  test('should toggle user skill state', async ({ page }) => {
    // Click disable button (停用)
    await page.getByTitle('停用').first().click();
    // After disable, the button should change to enable (启用)
    await expect(page.getByTitle('启用').first()).toBeVisible({ timeout: 10_000 });
    // Click enable
    await page.getByTitle('启用').first().click();
    await expect(page.getByTitle('停用').first()).toBeVisible({ timeout: 10_000 });
  });

  test('should show test results after test run', async ({ page }) => {
    const testBtn = page.getByTitle('测试运行').first();
    await testBtn.click();
    // Wait for results to appear
    await expect(page.getByText(/测试结果|测试失败/)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/耗时：42ms/)).toBeVisible();
    await expect(page.getByText(/证据引用：1 条/)).toBeVisible();
  });

  test('should approve pending skill request', async ({ page }) => {
    await page.getByRole('button', { name: '审批' }).click();

    await expect(page.getByText('该 Skill 请求访问草稿内容以执行润色。')).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: '批准' }).click();
    await expect(page.getByText('审批已记录：批准')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('暂无待审批请求')).toBeVisible({ timeout: 10_000 });
  });

  test('should route high-risk enable through approval tab', async ({ page }) => {
    const highRiskCard = page.locator('div', { has: page.locator('h4', { hasText: '联网检索 Skill' }) }).first();
    await highRiskCard.getByTitle('启用').click();

    await expect(page.getByText('启用前需要审批')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Enable high-risk user skill permissions: network')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: '批准' })).toBeVisible();
  });

  test('should reveal machine-readable security policy for high-risk skills', async ({ page }) => {
    const highRiskCard = page.locator('div', { has: page.locator('h4', { hasText: '联网检索 Skill' }) }).first();

    await page.getByRole('button', { name: '查看安全策略：联网检索 Skill' }).click();

    await expect(highRiskCard.getByText('安全策略')).toBeVisible({ timeout: 10_000 });
    await expect(highRiskCard.getByText('风险：high')).toBeVisible();
    await expect(highRiskCard.getByText('block_high_risk_permission')).toBeVisible();
    await expect(highRiskCard.getByText('High-risk Skill permissions are blocked by the current runtime')).toBeVisible();
    await expect(highRiskCard.getByText('network_allowlist_with_timeout')).toBeVisible();
  });

  test('should uninstall user skill with confirmation preview', async ({ page }) => {
    await page.getByTitle('卸载').first().click();

    await expect(page.getByRole('alertdialog', { name: '确认卸载 Skill' })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/C:\\managed\\.rollback_snapshots/)).toBeVisible();
    await page.getByRole('button', { name: '确认卸载' }).click();
    await expect(page.getByText('已卸载：文献润色 Skill')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('h4', { hasText: '文献润色 Skill' })).toHaveCount(0);
  });

  test('should rollback user skill from latest snapshot', async ({ page }) => {
    await page.getByTitle('回滚').first().click();

    await expect(page.getByRole('dialog', { name: '回滚 Skill' })).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: '开始回滚' }).click();
    await expect(page.getByText('已回滚：文献润色 Skill')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/恢复路径：C:\\managed\\user.prompt.polish/)).toBeVisible();
  });

  test('should switch to audit tab and show events', async ({ page }) => {
    await page.getByRole('button', { name: '审计日志' }).click();
    await expect(page.getByText('EXECUTION_COMPLETED')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Skill test run completed in the E2E fixture.')).toBeVisible();
  });
});
