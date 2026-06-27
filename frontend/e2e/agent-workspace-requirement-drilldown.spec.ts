import { expect, test } from '@playwright/test';
import type { Page, Route } from '@playwright/test';

type JsonValue = boolean | number | string | null | JsonValue[] | { [key: string]: JsonValue };

async function fulfillJson(route: Route, body: JsonValue, status = 200): Promise<void> {
  const resourceType = route.request().resourceType();
  if (resourceType !== 'fetch' && resourceType !== 'xhr') {
    await route.continue();
    return;
  }

  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function installAgentWorkspaceSmokeMocks(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });
  await page.route('**/resources/projects**', (route) => fulfillJson(route, []));
  await page.route('**/api/mcp/pending-calls**', (route) => fulfillJson(route, []));
  await page.route('**/api/**', (route) => {
    if (route.request().url().includes('/api/mcp/pending-calls')) {
      return route.fallback();
    }
    return fulfillJson(route, {});
  });
}

test('desktop acceptance route exposes read-only requirement drilldown evidence', async ({ page }) => {
  await installAgentWorkspaceSmokeMocks(page);

  await page.goto('/__desktop_acceptance/agent-workspace', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('app-main')).toBeVisible({ timeout: 20_000 });

  const acceptanceSurface = page.getByTestId('desktop-acceptance-agent-workspace');
  await expect(acceptanceSurface).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Agent Workspace', exact: true })).toBeVisible();

  const workspaceState = page.getByRole('region', { name: 'Workspace state visibility' });
  await expect(workspaceState).toBeVisible();
  await expect(workspaceState.getByText('workspace ready')).toBeVisible();
  await expect(workspaceState.getByText('read-only true').first()).toBeVisible();
  await expect(workspaceState.getByText('goal-state visible')).toBeVisible();
  await expect(workspaceState.getByText('requirement status visible')).toBeVisible();
  await expect(workspaceState.getByText('full goal status visible')).toBeVisible();

  const requirementDrilldown = workspaceState.getByRole('region', { name: 'Requirement evidence drilldown' });
  await expect(requirementDrilldown).toBeVisible();
  await expect(requirementDrilldown.getByText('Requirement Evidence')).toBeVisible();
  await expect(requirementDrilldown.getByText('drilldown visible')).toBeVisible();
  await expect(requirementDrilldown.getByText('read-only true')).toBeVisible();
  await expect(requirementDrilldown.getByText('evidence 4')).toBeVisible();
  await expect(requirementDrilldown.getByText('N74-wiki-import-desktop-acceptance · proved')).toBeVisible();
  await expect(requirementDrilldown.getByText('frontend/src/pages/DesktopAcceptanceAgentWorkspace.tsx · Desktop acceptance fixture renders WikiImportRecoveryPanel with local Markdown import runtime recovery metadata.')).toBeVisible();
  await expect(requirementDrilldown.getByText('frontend/src/pages/DesktopAcceptanceAgentWorkspace.test.tsx · Role-scoped test proves Wiki import recovery visibility, review-gated metadata, and no raw route or local path leakage.')).toBeVisible();
  await expect(requirementDrilldown.getByText('boundary No push, tag, release, deploy, external upload, approval execution, or Zotero DB mutation.')).toBeVisible();

  const crosslinks = page.getByRole('region', { name: 'Research action crosslinks' });
  await expect(crosslinks.getByText('Research Action Crosslinks')).toBeVisible();
  await expect(crosslinks.getByText('lifecycle read-only true')).toBeVisible();
  await expect(crosslinks.getByText('handoff action refs 1')).toBeVisible();
  await expect(crosslinks.getByText('Do not execute approvals from the handoff action-lifecycle recovery bundle.')).toBeVisible();

  await expect(page.getByText('full goal The long-running Scholar AI research workflow spine remains active, not complete.')).toBeVisible();
  await expect(page.getByText('C:\\Users\\xiao')).toHaveCount(0);
  await expect(page.getByText('C:\\Users\\Alice\\private\\desktop-acceptance.pdf')).toHaveCount(0);
  await expect(page.getByText('[redacted-local-path]').first()).toBeVisible();
});
