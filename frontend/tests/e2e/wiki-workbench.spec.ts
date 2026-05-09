/**
 * E2E: Wiki Workbench (LMWR-466)
 *
 * Uses the existing Playwright/Vite E2E harness with mocked API responses.
 * This is a browser preview gate for the future independent-window app, so it
 * checks core workflows without expanding visual/responsive scope.
 */
import { expect, test } from '@playwright/test';
import { installE2eApiMocks } from './mockApi';

test.describe('Wiki Workbench E2E', () => {
  test.beforeEach(async ({ page }) => {
    await installE2eApiMocks(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main')).toBeVisible({ timeout: 10_000 });
  });

  test('loads the Wiki route from the sidebar and renders status', async ({ page }) => {
    await page.getByRole('link', { name: 'Wiki' }).click();

    await expect(page).toHaveURL(/\/wiki$/);
    await expect(page.getByRole('heading', { name: /Wiki 当前保持|Wiki 已启用|正在同步/ })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('heading', { name: 'Wiki 工作台状态面' })).toBeVisible();
    await expect(page.getByText(/^enabled$/)).toBeVisible();
    await expect(page.getByText(/^stale: no$/)).toBeVisible();
    await expect(page.getByText('Graph JSON')).toBeVisible();
    await expect(page.getByText('Query Index')).toBeVisible();
    await expect(page.getByText('wiki_root')).toBeVisible();
  });

  test('opens a deep-linked page preview from the URL', async ({ page }) => {
    await page.goto('/wiki?page=sources%2Fpaper-a.md', { waitUntil: 'domcontentloaded' });

    await expect(page.getByRole('heading', { name: 'Wiki 页面预览' })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('sources/paper-a.md').first()).toBeVisible();
    await expect(page.getByText('Laser Welding Paper A').first()).toBeVisible();
    await expect(page.getByText('Laser welding quality is sensitive to process window stability.').first()).toBeVisible();
    await expect(page.getByText('文内引用与证据预警')).not.toBeVisible();
  });

  test('selects a page from the list and shows claim evidence preview', async ({ page }) => {
    await page.goto('/wiki', { waitUntil: 'domcontentloaded' });

    await expect(page.getByRole('heading', { name: 'Wiki 页面列表' })).toBeVisible({ timeout: 15_000 });
    await page.getByRole('button', { name: /Claim: Graph context improves recall/ }).click();

    await expect(page).toHaveURL(/page=claims%2Fclaim-a\.md/);
    await expect(page.getByText('claims/claim-a.md').first()).toBeVisible();
    await expect(page.getByText('Graph context improves recall for linked technical concepts.').first()).toBeVisible();
    await expect(page.getByText('evidence_refs')).toBeVisible();
  });

  test('runs compile dry-run and keeps output non-writing', async ({ page }) => {
    await page.goto('/wiki', { waitUntil: 'domcontentloaded' });

    await expect(page.getByRole('heading', { name: 'Wiki Compile Dry-Run' })).toBeVisible({ timeout: 15_000 });
    await page.getByPlaceholder('例如 source:paper-001').fill('source-paper-a');
    await page.getByRole('button', { name: '执行 dry-run 推演' }).click();

    await expect(page.getByText('Dry-run console')).toBeVisible();
    await expect(page.getByText('1560')).toBeVisible();
    await expect(page.getByText('workspace_artifacts/generated/wiki/sources/source-paper-a.md')).toBeVisible();
    await expect(page.getByText('Compile dry-run completed without writing wiki pages.')).toBeVisible();
    await expect(page.getByText('written')).toBeVisible();
  });

  test('renders doctor, review, and graph governance surfaces', async ({ page }) => {
    await page.goto('/wiki', { waitUntil: 'domcontentloaded' });

    await expect(page.getByRole('heading', { name: '健康诊断只读面' })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Citation density')).toBeVisible();
    await expect(page.getByText('wiki doctor --repair safe')).toBeVisible();

    await expect(page.getByRole('heading', { name: '治理队列只读面' })).toBeVisible();
    await expect(page.getByText('Review graph recall claim')).toBeVisible();
    await expect(page.getByText('Approved source summary')).toBeVisible();

    await expect(page.getByRole('heading', { name: 'Graph debug 视图' })).toBeVisible();
    await expect(page.getByText(/^2$/).first()).toBeVisible();
    await expect(page.getByText(/^1$/).first()).toBeVisible();
    await expect(page.getByText('Laser Welding Paper A').first()).toBeVisible();
    await expect(page.getByText('cites')).toBeVisible();
  });
});
