/**
 * E2E Smoke: Navigation & Page Load (TASK-179 / TASK-192)
 *
 * Verifies that core routes render without crash.
 * Does NOT require a running backend — uses Vite dev server + mock API.
 *
 * TASK-192 stability notes:
 * - Uses `waitUntil: 'domcontentloaded'` instead of 'networkidle' because
 *   some pages make API calls that may not complete even with mocks.
 * - Then waits for `<main>` element which is in MainLayout.tsx.
 * - Each test clears storage via `installE2eApiMocks` (addInitScript).
 */
import { test, expect } from '@playwright/test';
import { installE2eApiMocks } from './mockApi';

test.beforeEach(async ({ page }) => {
  await installE2eApiMocks(page);
});

// -------------------------------------------------------------------
// Core route smoke: each page loads without crash
// -------------------------------------------------------------------

const routes = [
  { path: '/', name: 'Workbench' },
  { path: '/knowledge', name: 'KnowledgeBase' },
  { path: '/projects', name: 'Projects' },
  { path: '/settings', name: 'Settings' },
  { path: '/writing', name: 'WritingOverview' },
  { path: '/chat', name: 'IntelligentChat' },
  { path: '/jobs', name: 'Jobs' },
];

for (const route of routes) {
  test(`${route.name} page loads without crash at ${route.path}`, async ({ page }) => {
    // Warm up by going to root first (fixes intermittent 500 on direct navigation to some routes on Windows)
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main')).toBeVisible({ timeout: 10_000 });

    await page.goto(route.path, { waitUntil: 'domcontentloaded' });
    // Main content area should become visible (from MainLayout)
    await expect(page.locator('main')).toBeVisible({ timeout: 20_000 });
    // No React error overlay
    await expect(page.locator('text=Unhandled Runtime Error')).not.toBeVisible();
  });
}

// -------------------------------------------------------------------
// Sidebar navigation (Stable alternative to direct navigation)
// -------------------------------------------------------------------

test('navigation between pages via sidebar', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main')).toBeVisible();
  
  const sidebarLinks = [
    { name: /灵感/, path: '/inspiration' },
    { name: /项目/, path: '/projects' },
    { name: /知识库/, path: '/knowledge' },
    { name: /设置/, path: '/settings' },
    { name: /任务/, path: '/jobs' },
    { name: /卷次/, path: '/volume' },
  ];

  for (const link of sidebarLinks) {
    await page.getByRole('link', { name: link.name }).click();
    await expect(page).toHaveURL(new RegExp(link.path));
    await expect(page.locator('main')).toBeVisible({ timeout: 10_000 });
  }
});

// -------------------------------------------------------------------
// Feature-specific smoke
// -------------------------------------------------------------------

test('Workbench: empty project state', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main')).toBeVisible({ timeout: 20_000 });
  // At least one visible text element in main area
  const mainText = await page.locator('main').textContent();
  expect(mainText).toBeTruthy();
});

test('Writing: page loads writing overview', async ({ page }) => {
  await page.goto('/writing', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main')).toBeVisible({ timeout: 20_000 });
  // Writing overview should have link to sub-pages
  const writingLinks = page.locator('a[href^="/writing"]');
  const count = await writingLinks.count();
  expect(count).toBeGreaterThan(0);
});

test('Settings: page renders with sections', async ({ page }) => {
  await page.goto('/settings', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main')).toBeVisible({ timeout: 20_000 });
  const mainContent = await page.locator('main').textContent();
  expect(mainContent).toBeTruthy();
});
