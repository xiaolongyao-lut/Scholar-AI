import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { ApiConfigSummaryRow, SETTINGS_NAV_TABS, SettingsPage } from './Settings';
import { buildSettingsSectionPath, resolveInitialSection } from './settingsSections';

vi.mock('axios', () => {
  const get = vi.fn(async (url: string) => {
    if (url.endsWith('/health')) {
      return { data: { status: 'ok' } };
    }
    return { data: {} };
  });
  const post = vi.fn(async () => ({ data: { ok: true } }));
  const apiClient = {
    get,
    post,
    request: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  };
  return {
    default: {
      create: vi.fn(() => apiClient),
      get,
      post,
      isAxiosError: () => false,
    },
    isAxiosError: () => false,
  };
});

vi.mock('@/services/featureFlagsApi', () => ({
  listFeatureFlags: vi.fn(async () => [
    {
      name: 'wiki',
      label: 'Wiki 知识沉淀',
      description: '开启 Wiki 工作台。',
      default: false,
      env_var: null,
      current: false,
      source: 'default',
    },
  ]),
  setFeatureFlag: vi.fn(async (name: string, enabled: boolean) => ({
    name,
    label: 'Wiki 知识沉淀',
    description: '开启 Wiki 工作台。',
    default: false,
    env_var: null,
    current: enabled,
    source: 'override',
  })),
}));

vi.mock('@/services/settingsApi', () => ({
  getUnifiedSettings: vi.fn(async () => ({
    api: {
      chat: {
        provider: '自定义服务',
        base_url: 'https://example.invalid/v1',
        model: 'chat-model',
        has_api_key: true,
        api_key_masked: '****',
        updated_at: '2026-05-29T12:00:00+08:00',
      },
      embedding: {
        provider: '自定义服务',
        base_url: 'https://example.invalid/v1',
        model: 'embedding-model',
        has_api_key: true,
        api_key_masked: '****',
        updated_at: '2026-05-29T12:00:00+08:00',
      },
      rerank: {
        provider: '自定义服务',
        base_url: 'https://example.invalid/v1',
        model: 'rerank-model',
        has_api_key: true,
        api_key_masked: '****',
        updated_at: '2026-05-29T12:00:00+08:00',
      },
    },
    credentials: {
      total: 1,
      enabled: 1,
      generation: 1,
      embedding: 0,
      rerank: 0,
    },
    feature_flags: [
      {
        name: 'wiki',
        label: 'Wiki 知识沉淀',
        current: false,
      },
    ],
  })),
}));

describe('Settings navigation', () => {
  it('keeps API-adjacent legacy sections out of the visible left navigation', () => {
    const visibleSectionIds = SETTINGS_NAV_TABS.map((tab) => tab.id);

    expect(visibleSectionIds).toEqual([
      'api',
      'workspace',
      'skills',
      'mcp',
      'discussion',
      'citation-styles',
      'experimental',
      'logs',
    ]);
    expect(visibleSectionIds).not.toContain('chat');
    expect(visibleSectionIds).not.toContain('embedding');
    expect(visibleSectionIds).not.toContain('rerank');
    expect(visibleSectionIds).not.toContain('semantic-routing');
    expect(visibleSectionIds).not.toContain('sampling');
  });

  it('keeps legacy deep links working after duplicate sections were hidden', () => {
    expect(resolveInitialSection('?section=chat')).toBe('chat');
    expect(resolveInitialSection('?section=embedding')).toBe('semantic-routing');
    expect(resolveInitialSection('?section=rerank')).toBe('semantic-routing');
    expect(resolveInitialSection('?section=sampling')).toBe('chat');
    expect(resolveInitialSection('?section=experimental')).toBe('experimental');
    expect(buildSettingsSectionPath('experimental')).toBe('/settings?section=experimental');
  });

  it('opens the feature switchboard from its deep link and keeps tab clicks reflected in the URL', async () => {
    window.history.replaceState(null, '', buildSettingsSectionPath('experimental'));

    render(<SettingsPage />);

    expect(await screen.findByText('Wiki 知识沉淀')).toBeInTheDocument();
    expect(window.location.search).toBe('?section=experimental');

    fireEvent.click(screen.getByRole('button', { name: 'API 配置' }));

    expect(window.location.search).toBe('?section=api');
  });

  it('keeps the API test action immediately before the configure action', () => {
    render(
      <ApiConfigSummaryRow
        label="聊天与生成"
        config={{
          provider: '自定义服务',
          base_url: 'https://example.invalid/v1',
          model: 'custom-chat',
          has_api_key: true,
          api_key_masked: '****',
          updated_at: '2026-05-29T12:00:00+08:00',
        }}
        subsystem="chat"
        targetSection="chat"
        onOpen={() => undefined}
      />,
    );

    expect(screen.getByText('聊天与生成')).toBeInTheDocument();
    const buttons = screen.getAllByRole('button');
    expect(buttons.map((button) => button.textContent?.trim())).toEqual(['测试', '配置']);
  });
});
