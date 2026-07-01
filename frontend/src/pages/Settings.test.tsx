import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { ApiConfigSummaryRow, SETTINGS_NAV_TABS, SettingsPage } from './Settings';
import { buildSettingsSectionPath, resolveInitialSection } from './settingsSections';
import { CredentialsSection } from '@/components/settings/CredentialsSection';
import * as pdfBackendApi from '@/services/pdfBackendApi';
import * as credentialsApi from '@/services/credentialsApi';

vi.mock('axios', () => {
  const get = vi.fn(async (url: string) => {
    if (url.endsWith('/health')) {
      return { data: { status: 'ok' } };
    }
    if (url.endsWith('/api/chat/config')) {
      return {
        data: {
          provider: '本地 DeepSeek',
          base_url: 'http://127.0.0.1:8000/v1',
          model: 'deepseek-r1',
          has_api_key: false,
          api_key_masked: '',
          updated_at: '2026-07-01T00:00:00+08:00',
        },
      };
    }
    if (url.endsWith('/api/chat/context-compression')) {
      return {
        data: {
          enabled: true,
          trigger_tokens: 24000,
          target_tokens: 2000,
          keep_recent_turns: 6,
          updated_at: '2026-07-01T00:00:00+08:00',
        },
      };
    }
    if (url.endsWith('/api/embedding/config')) {
      return {
        data: {
          provider: '本地 Embedding',
          base_url: 'http://127.0.0.1:8010/v1',
          model: 'bge-m3',
          has_api_key: false,
          api_key_masked: '',
          updated_at: '2026-07-01T00:00:00+08:00',
        },
      };
    }
    if (url.endsWith('/api/rerank/config')) {
      return {
        data: {
          provider: '本地 Rerank',
          base_url: 'http://127.0.0.1:8020/v1',
          model: 'bge-reranker-v2-m3',
          has_api_key: false,
          api_key_masked: '',
          updated_at: '2026-07-01T00:00:00+08:00',
        },
      };
    }
    if (url.endsWith('/api/embedding/local-status')) {
      return {
        data: {
          available: false,
          disabled: false,
          weights_present: true,
          allow_download: false,
          model_name: 'BAAI/bge-m3',
          device: 'cpu',
          device_source: 'auto_detected',
          batch_size: 32,
          loaded: false,
          hf_cache_dir: 'C:\\Users\\xiao\\.cache\\huggingface\\hub',
          unavailable_reason: '缺少 Python 依赖：torch, sentence-transformers。',
        },
      };
    }
    if (url.endsWith('/api/rerank/local-status')) {
      return {
        data: {
          available: false,
          disabled: false,
          weights_present: true,
          allow_download: false,
          model_name: 'BAAI/bge-reranker-v2-m3',
          device: 'cpu',
          device_source: 'auto_detected',
          max_length: 512,
          batch_size: 8,
          loaded: false,
          hf_cache_dir: 'C:\\Users\\xiao\\.cache\\huggingface\\hub',
          unavailable_reason: '缺少 Python 依赖：torch, transformers。',
        },
      };
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
      name: 'pdf_parser_marker',
      label: 'PDF 结构化解析(marker)',
      description: '启用本地 Marker 解析后端。',
      default: false,
      env_var: null,
      current: false,
      source: 'default',
    },
  ]),
  setFeatureFlag: vi.fn(async (name: string, enabled: boolean) => ({
    name,
    label: 'PDF 结构化解析(marker)',
    description: '启用本地 Marker 解析后端。',
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
      ocr: 0,
    },
    feature_flags: [
      {
        name: 'pdf_parser_marker',
        label: 'PDF 结构化解析(marker)',
        current: false,
      },
    ],
  })),
}));

vi.mock('@/services/credentialsApi', () => ({
  listCredentials: vi.fn(async () => []),
  createCredential: vi.fn(async (body: Record<string, unknown>) => ({
    credential_id: 'cred_ocr_1',
    category: body.category,
    provider: body.provider,
    model: body.model,
    base_url: body.base_url,
    protocol: body.protocol,
    enabled: body.enabled ?? true,
    priority: 100,
    tags: [],
    strategy_hint: body.strategy_hint ?? 'medium',
    trust_source: body.trust_source ?? 'runtime_user_confirmed',
    notes: body.notes ?? '',
    sampling_override: null,
    api_key_masked: 'sk-****',
    has_api_key: true,
    fingerprint: 'fp',
    fingerprint_version: 'v1',
    created_at: '2026-07-01T00:00:00+08:00',
    updated_at: '2026-07-01T00:00:00+08:00',
  })),
  deleteCredential: vi.fn(async () => undefined),
  testCredential: vi.fn(async () => ({
    credential_id: 'cred_ocr_1',
    status: 'ok',
    probed: false,
    decision: {
      allowed: true,
      reason: 'skip_dns_passthrough',
      trust_source: 'runtime_user_confirmed',
      scheme: 'https',
      host: 'api.mistral.ai',
      port: null,
      path: '/v1',
      resolved_ips: [],
      rejected_ips: [],
      skipped_network: true,
    },
    probe: {
      probed: false,
      url_used: 'https://api.mistral.ai/v1',
      method: 'CONFIG',
      ok: true,
      reachable: false,
      capability_verdict: 'ocr_config_ready',
      checks: {
        base_url_present: true,
        api_key_present: true,
        model_present: true,
      },
    },
  })),
  updateCredential: vi.fn(async () => undefined),
  isCredentialNotFoundError: vi.fn(() => false),
  applyCredentialToSubsystem: vi.fn(async () => ({
    provider: '本地 DeepSeek',
    base_url: 'http://127.0.0.1:8000/v1',
    model: 'deepseek-r1',
    has_api_key: false,
    api_key_masked: '',
    updated_at: '2026-07-01T00:00:00+08:00',
  })),
}));

vi.mock('@/services/chatApi', () => ({
  discoverModels: vi.fn(async () => ({ ok: true, models: [] })),
}));

vi.mock('@/services/pdfBackendApi', () => ({
  fetchPdfBackendStatus: vi.fn(async () => ({
    active_backend: 'pymupdf',
    active_source: 'default',
    env_var_name: 'LITERATURE_ASSISTANT_PDF_BACKEND',
    env_var_value: null,
    external_backends_supported: true,
    install_hint: '默认使用 PyMuPDF。',
    feature_flag_name: 'pdf_parser_marker',
    feature_flag_enabled: false,
    marker_installed: false,
    marker_version: null,
    marker_install_hint: 'pip install marker-pdf',
    ocr_policy: 'auto',
    ocr_configured_engine: null,
    ocr_selected_engine: 'rapidocr',
    ocr_language: 'en',
    ocr_config_source: 'default',
    ocr_warning: null,
  })),
  fetchOcrStatus: vi.fn(async () => ({
    policy: 'auto',
    configured_engine: null,
    selected_engine: 'rapidocr',
    language: 'en',
    source: 'default',
    engine_config: {},
    available_engines: [
      {
        name: 'rapidocr',
        display_name: 'RapidOCR',
        engine_type: 'local',
        available: true,
        requires_network: false,
        unavailable_reason: null,
        readiness_status: 'ready',
        readiness_blockers: [],
        next_safe_local_actions: [],
      },
      {
        name: 'remote_api',
        display_name: 'Remote OCR API',
        engine_type: 'remote',
        available: false,
        requires_network: true,
        unavailable_reason: '需要配置服务地址和上传确认',
        readiness_status: 'configuration_required',
        readiness_blockers: ['missing base_url'],
        next_safe_local_actions: [],
      },
      {
        name: 'windows',
        display_name: 'Windows OCR',
        engine_type: 'local',
        available: true,
        requires_network: false,
        unavailable_reason: null,
        readiness_status: 'ready',
        readiness_blockers: [],
        next_safe_local_actions: [],
      },
      {
        name: 'paddleocr_gpu',
        display_name: 'PaddleOCR GPU',
        engine_type: 'local',
        available: false,
        requires_network: false,
        unavailable_reason: "paddleocr and paddlepaddle runtime module 'paddle' are not installed in the active Python runtime",
        readiness_status: 'dependency_missing',
        readiness_blockers: [
          "paddleocr and paddlepaddle runtime module 'paddle' are not installed in the active Python runtime",
        ],
        next_safe_local_actions: [],
      },
    ],
    warning: null,
    next_safe_local_actions: [],
  })),
  saveOcrEngineSelection: vi.fn(async (payload: {
    policy: 'auto' | 'none' | 'engine';
    engine?: string | null;
    language: string;
    engine_config: Record<string, unknown>;
  }) => ({
    saved: true,
    config_path: 'runtime_state/ocr.json',
    status: {
      policy: payload.policy,
      configured_engine: payload.engine ?? null,
      selected_engine: payload.engine ?? 'rapidocr',
      language: payload.language,
      source: 'runtime',
      engine_config: payload.engine_config,
      available_engines: [],
      warning: null,
      next_safe_local_actions: [],
    },
  })),
  checkOcrHealth: vi.fn(async (payload: { engine?: string | null }) => ({
    ok: true,
    detail: 'ok',
    engine: payload.engine ?? 'rapidocr',
    latency_ms: 12,
    readiness_status: 'ready',
    readiness_blockers: [],
    next_safe_local_actions: [],
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
    expect(visibleSectionIds).not.toContain('ocr');
    expect(visibleSectionIds).not.toContain('semantic-routing');
    expect(visibleSectionIds).not.toContain('sampling');
  });

  it('keeps legacy deep links working after duplicate sections were hidden', () => {
    expect(resolveInitialSection('?section=chat')).toBe('chat');
    expect(resolveInitialSection('?section=ocr')).toBe('api');
    expect(resolveInitialSection('?section=embedding')).toBe('semantic-routing');
    expect(resolveInitialSection('?section=rerank')).toBe('semantic-routing');
    expect(resolveInitialSection('?section=sampling')).toBe('chat');
    expect(resolveInitialSection('?section=experimental')).toBe('experimental');
    expect(buildSettingsSectionPath('ocr')).toBe('/settings?section=api');
    expect(buildSettingsSectionPath('experimental')).toBe('/settings?section=experimental');
  });

  it('opens the feature switchboard from its deep link and keeps tab clicks reflected in the URL', async () => {
    window.history.replaceState(null, '', buildSettingsSectionPath('experimental'));

    render(<SettingsPage />);

    expect(await screen.findByText('PDF 结构化解析(marker)')).toBeInTheDocument();
    expect(screen.getByText('检索主链已升级 · 默认开启')).toBeInTheDocument();
    expect(window.location.search).toBe('?section=experimental');

    fireEvent.click(screen.getByRole('button', { name: 'API 配置' }));

    expect(window.location.search).toBe('?section=api');
  });

  it('shows local-first OCR controls from the API settings deep link', async () => {
    window.history.replaceState(null, '', buildSettingsSectionPath('ocr'));

    render(<SettingsPage />);

    expect(await screen.findByRole('heading', { name: 'OCR 设置' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'OCR 识别' })).not.toBeInTheDocument();
    expect(window.location.search).toBe('?section=api');
    expect(screen.getByText(/默认优先使用本地 OCR/)).toBeInTheDocument();
    expect(screen.getByText(/用途：决定什么时候触发 OCR/)).toBeInTheDocument();
    expect(screen.getByLabelText('选择引擎')).toBeInTheDocument();
    expect(screen.getByText('自动选择不是脚本，也没有独立路径。')).toBeInTheDocument();
    expect(screen.getByText(/paddleocr_gpu → rapidocr → windows → remote_api/)).toBeInTheDocument();
    expect(screen.getByText(/RapidOCR \/ PaddleOCR GPU 填装好依赖的 python\.exe/)).toBeInTheDocument();
    expect(screen.getByText('RapidOCR')).toBeInTheDocument();
    expect(screen.getByText('Windows OCR')).toBeInTheDocument();
    expect(screen.getByText('Remote OCR API')).toBeInTheDocument();
    expect(screen.queryByText('服务地址')).not.toBeInTheDocument();
    expect(screen.queryByText('外部 Python 路径（可选）')).not.toBeInTheDocument();
  });

  it('saves and health-checks the selected local OCR engine', async () => {
    window.history.replaceState(null, '', buildSettingsSectionPath('ocr'));

    render(<SettingsPage />);

    await screen.findByRole('heading', { name: 'OCR 设置' });

    fireEvent.change(screen.getByLabelText('OCR 策略'), { target: { value: 'engine' } });
    fireEvent.change(screen.getByLabelText('选择引擎'), { target: { value: 'rapidocr' } });

    expect(screen.getByText('RapidOCR Python 路径（可选）')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '检查当前引擎' }));
    await waitFor(() => {
      expect(pdfBackendApi.checkOcrHealth).toHaveBeenCalledWith({
        engine: 'rapidocr',
        engine_config: {
          timeout_seconds: 300,
          language: 'en',
        },
      });
    });

    fireEvent.click(screen.getByRole('button', { name: '保存 OCR 设置' }));
    await waitFor(() => {
      expect(pdfBackendApi.saveOcrEngineSelection).toHaveBeenCalledWith({
        policy: 'engine',
        engine: 'rapidocr',
        language: 'en',
        engine_config: {
          timeout_seconds: 300,
          language: 'en',
        },
      });
    });
  });

  it('shows the PaddleOCR python.exe field instead of implying a source folder is enough', async () => {
    window.history.replaceState(null, '', buildSettingsSectionPath('ocr'));

    render(<SettingsPage />);

    await screen.findByRole('heading', { name: 'OCR 设置' });

    fireEvent.change(screen.getByLabelText('OCR 策略'), { target: { value: 'engine' } });
    fireEvent.change(screen.getByLabelText('选择引擎'), { target: { value: 'paddleocr_gpu' } });

    expect(screen.getByText('PaddleOCR Python 路径（可选）')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('C:\\path\\to\\paddleocr-venv\\Scripts\\python.exe')).toBeInTheDocument();
    expect(screen.getByText(/下载的 PaddleOCR-main 源码目录本身不会被当作运行时/)).toBeInTheDocument();
    expect(screen.getByText('PaddleOCR 调用方法')).toBeInTheDocument();
  });

  it('explains how locally deployed chat models such as DeepSeek appear in the UI', async () => {
    window.history.replaceState(null, '', buildSettingsSectionPath('chat'));

    render(<SettingsPage />);

    expect(await screen.findByText('问答模型按兼容 API 服务显示，不扫描本机模型文件。')).toBeInTheDocument();
    expect(screen.getByText(/本地部署的 DeepSeek、Qwen、Llama 等模型/)).toBeInTheDocument();
    expect(screen.getByText(/设置页显示保存后的供应商、服务地址和模型名称/)).toBeInTheDocument();
    expect(screen.getByText(/“获取模型”只读取当前服务的模型列表接口/)).toBeInTheDocument();
  });

  it('shows visible local embedding and rerank runtime boundaries', async () => {
    window.history.replaceState(null, '', buildSettingsSectionPath('semantic-routing'));

    render(<SettingsPage />);

    expect(await screen.findByText('Embedding 可以接远程服务、本地兼容 API，或使用本机进程加载。')).toBeInTheDocument();
    expect(screen.getByText('Rerank 可以接兼容 API 服务，也可以使用本机进程加载。')).toBeInTheDocument();
    expect(await screen.findByText(/Embedding本机进程加载（无需 API）：不可用/)).toBeInTheDocument();
    expect(await screen.findByText(/Rerank本机进程加载（无需 API）：不可用/)).toBeInTheDocument();
    expect(screen.getByText(/不可用原因：缺少 Python 依赖：torch, sentence-transformers。/)).toBeInTheDocument();
    expect(screen.getAllByText(/这不是因为没有填写 API/)).toHaveLength(2);
    expect(screen.getByText(/界面显示当前后端状态，不会扫描硬盘上的所有模型文件/)).toBeInTheDocument();
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

  it('creates OCR credentials with provider presets and visible trust choices', async () => {
    render(<CredentialsSection />);

    fireEvent.click(await screen.findByRole('button', { name: /新增 API/ }));
    fireEvent.change(screen.getByLabelText('用途'), { target: { value: 'ocr' } });

    expect(screen.getByRole('button', { name: 'Mistral OCR' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'MinerU 文档解析' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /自定义服务，已确认信任/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /暂不信任/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Mistral OCR' }));

    expect(screen.getByLabelText('提供商')).toHaveValue('Mistral');
    expect(screen.getByLabelText('模型')).toHaveValue('mistral-ocr-latest');
    expect(screen.getByLabelText('协议')).toHaveValue('ocr');
    expect(screen.getByLabelText('服务地址')).toHaveValue('https://api.mistral.ai/v1');

    fireEvent.change(screen.getByLabelText('访问密钥'), { target: { value: 'sk-test-ocr-key' } });
    fireEvent.click(screen.getByRole('button', { name: '测试连接' }));
    expect(screen.getByText(/OCR 配置可保存/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    await waitFor(() => {
      expect(credentialsApi.createCredential).toHaveBeenCalledWith(expect.objectContaining({
        category: 'ocr',
        provider: 'Mistral',
        model: 'mistral-ocr-latest',
        base_url: 'https://api.mistral.ai/v1',
        protocol: 'ocr',
        trust_source: 'runtime_user_confirmed',
      }));
    });
  });
});
