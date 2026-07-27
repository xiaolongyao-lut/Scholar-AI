import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { ApiConfigSummaryRow, SETTINGS_NAV_TABS, SettingsPage } from './Settings';
import { buildSettingsSectionPath, resolveInitialSection } from './settingsSections';
import { CredentialsSection } from '@/components/settings/CredentialsSection';
import * as pdfBackendApi from '@/services/pdfBackendApi';
import * as credentialsApi from '@/services/credentialsApi';
import type { RuntimeCredentialPublic } from '@/services/credentialsApi';

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
          model_auto_compact_token_limit: 150000,
          trigger_tokens: 150000,
          model_context_window: 258400,
          tool_output_token_limit: 8000,
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
          hf_cache_dir: 'C:\\Users\\example-user\\.cache\\huggingface\\hub',
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
          hf_cache_dir: 'C:\\Users\\example-user\\.cache\\huggingface\\hub',
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
  runOcrExecutionProbe: vi.fn(async () => ({
    schema_version: 'scholar-ai-ocr-execution-probe/v1',
    confirmed: true,
    engine: 'rapidocr',
    engine_type: 'local',
    requires_network: false,
    language: 'en',
    input_kind: 'image_base64',
    input_bytes: 4096,
    input_sha256: 'a'.repeat(64),
    text_length: 45,
    text_sha256: 'b'.repeat(64),
    text_preview: 'SCHOLAR AI OCR TEST 2026\nPOSITION SAMPLE',
    duration_ms: 128,
    region_count: 1,
    region_samples: [
      {
        block_type: 'text',
        text_preview: 'POSITION SAMPLE',
        bbox: [0.125, 0.25, 0.5, 0.125],
      },
    ],
  })),
  classifyOcrExecutionProbeError: vi.fn((error: unknown) => {
    const status = typeof error === 'object' && error !== null && 'status' in error
      ? (error as { status?: unknown }).status
      : null;
    if (status === 502) {
      return {
        category: 'provider',
        title: 'OCR 服务执行失败',
        detail: '请求已进入真实 OCR 执行链路，但服务端未完成识别。请检查凭证、配额和模型设置。',
      };
    }
    return {
      category: 'unexpected',
      title: 'OCR 执行失败',
      detail: '未能完成本次 OCR 执行测试，请稍后重试。',
    };
  }),
}));

function makeOcrCredential(): RuntimeCredentialPublic {
  return {
    credential_id: 'cred_ocr_1',
    category: 'ocr',
    provider: 'Mistral',
    model: 'mistral-ocr-latest',
    base_url: 'https://api.mistral.ai/v1',
    protocol: 'ocr',
    enabled: true,
    priority: 100,
    tags: [],
    strategy_hint: 'medium',
    trust_source: 'runtime_user_confirmed',
    notes: '',
    sampling_override: null,
    api_key_masked: 'sk-****',
    has_api_key: true,
    fingerprint: 'fp',
    fingerprint_version: 'v1',
    created_at: '2026-07-01T00:00:00+08:00',
    updated_at: '2026-07-01T00:00:00+08:00',
  };
}

describe('Settings navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

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

  it('runs a readable disposable image through OCR and displays structured execution proof', async () => {
    const context = {
      fillStyle: '',
      font: '',
      textBaseline: 'alphabetic',
      fillRect: vi.fn(),
      fillText: vi.fn(),
    } as unknown as CanvasRenderingContext2D;
    const getContext = vi
      .spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockImplementation(() => context);
    const toDataUrl = vi
      .spyOn(HTMLCanvasElement.prototype, 'toDataURL')
      .mockReturnValue('data:image/png;base64,c3ludGhldGljLXBuZw==');

    try {
      window.history.replaceState(null, '', buildSettingsSectionPath('ocr'));
      render(<SettingsPage />);

      await screen.findByRole('heading', { name: 'OCR 设置' });
      const executionButton = screen.getByRole('button', { name: '执行 OCR 测试' });
      await waitFor(() => expect(executionButton).toBeEnabled());
      fireEvent.click(executionButton);

      await waitFor(() => {
        expect(pdfBackendApi.runOcrExecutionProbe).toHaveBeenCalledWith({
          confirm_execution: true,
          image_base64: 'c3ludGhldGljLXBuZw==',
          engine: 'rapidocr',
          engine_config: {
            timeout_seconds: 300,
            language: 'en',
          },
          language: 'en',
          preview_chars: 240,
        });
      });
      expect(context.fillText).toHaveBeenCalledWith('SCHOLAR AI OCR TEST 2026', 48, 70);
      expect(context.fillText).toHaveBeenCalledWith('POSITION SAMPLE', 48, 172);
      expect(await screen.findByText('OCR 执行已确认')).toBeInTheDocument();
      expect(screen.getByText((_, element) => (
        element?.tagName === 'PRE'
        && element.textContent === 'SCHOLAR AI OCR TEST 2026\nPOSITION SAMPLE'
      ))).toBeInTheDocument();
      expect(screen.getByText('识别区域：1')).toBeInTheDocument();
      expect(screen.getByText(/x 0\.125 · y 0\.250 · 宽 0\.500 · 高 0\.125/)).toBeInTheDocument();
    } finally {
      getContext.mockRestore();
      toDataUrl.mockRestore();
    }
  });

  it('keeps the OCR execution action busy and prevents duplicate submissions', async () => {
    const context = {
      fillStyle: '',
      font: '',
      textBaseline: 'alphabetic',
      fillRect: vi.fn(),
      fillText: vi.fn(),
    } as unknown as CanvasRenderingContext2D;
    const getContext = vi
      .spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockImplementation(() => context);
    const toDataUrl = vi
      .spyOn(HTMLCanvasElement.prototype, 'toDataURL')
      .mockReturnValue('data:image/png;base64,c3ludGhldGljLXBuZw==');
    let resolveProbe: ((value: Awaited<ReturnType<typeof pdfBackendApi.runOcrExecutionProbe>>) => void) | undefined;
    vi.mocked(pdfBackendApi.runOcrExecutionProbe).mockImplementationOnce(() => (
      new Promise((resolve) => { resolveProbe = resolve; })
    ));

    try {
      window.history.replaceState(null, '', buildSettingsSectionPath('ocr'));
      render(<SettingsPage />);

      await screen.findByRole('heading', { name: 'OCR 设置' });
      const executionButton = screen.getByRole('button', { name: '执行 OCR 测试' });
      await waitFor(() => expect(executionButton).toBeEnabled());
      fireEvent.click(executionButton);

      const busyButton = await screen.findByRole('button', { name: '正在执行 OCR 测试' });
      expect(busyButton).toBeDisabled();
      fireEvent.click(busyButton);
      expect(pdfBackendApi.runOcrExecutionProbe).toHaveBeenCalledTimes(1);

      resolveProbe?.({
        schema_version: 'scholar-ai-ocr-execution-probe/v1',
        confirmed: true,
        engine: 'rapidocr',
        engine_type: 'local',
        requires_network: false,
        language: 'en',
        input_kind: 'image_base64',
        input_bytes: 4096,
        input_sha256: 'a'.repeat(64),
        text_length: 45,
        text_sha256: 'b'.repeat(64),
        text_preview: 'SCHOLAR AI OCR TEST 2026\nPOSITION SAMPLE',
        duration_ms: 128,
        region_count: 0,
        region_samples: [],
      });
      await screen.findByRole('button', { name: '执行 OCR 测试' });
    } finally {
      getContext.mockRestore();
      toDataUrl.mockRestore();
    }
  });

  it('shows a categorized provider failure without claiming the OCR token expired', async () => {
    const context = {
      fillStyle: '',
      font: '',
      textBaseline: 'alphabetic',
      fillRect: vi.fn(),
      fillText: vi.fn(),
    } as unknown as CanvasRenderingContext2D;
    const getContext = vi
      .spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockImplementation(() => context);
    const toDataUrl = vi
      .spyOn(HTMLCanvasElement.prototype, 'toDataURL')
      .mockReturnValue('data:image/png;base64,c3ludGhldGljLXBuZw==');
    vi.mocked(pdfBackendApi.runOcrExecutionProbe).mockRejectedValueOnce({ status: 502 });

    try {
      window.history.replaceState(null, '', buildSettingsSectionPath('ocr'));
      render(<SettingsPage />);

      await screen.findByRole('heading', { name: 'OCR 设置' });
      const executionButton = screen.getByRole('button', { name: '执行 OCR 测试' });
      await waitFor(() => expect(executionButton).toBeEnabled());
      fireEvent.click(executionButton);

      expect(await screen.findByText('OCR 服务执行失败')).toBeInTheDocument();
      expect(screen.getByText(/请检查凭证、配额和模型设置/)).toBeInTheDocument();
      expect(screen.queryByText(/过期/)).not.toBeInTheDocument();
      expect(screen.queryByText('OCR 执行已确认')).not.toBeInTheDocument();
    } finally {
      getContext.mockRestore();
      toDataUrl.mockRestore();
    }
  });

  it('classifies an Axios provider response without claiming the OCR token expired', async () => {
    const actualPdfBackendApi = await vi.importActual<typeof import('@/services/pdfBackendApi')>(
      '@/services/pdfBackendApi',
    );

    expect(actualPdfBackendApi.classifyOcrExecutionProbeError({
      response: { status: 502 },
      isAxiosError: true,
    })).toEqual(expect.objectContaining({
      category: 'provider',
      title: 'OCR 服务执行失败',
    }));
  });

  it('classifies an Axios timeout without blaming the saved OCR credential', async () => {
    const actualPdfBackendApi = await vi.importActual<typeof import('@/services/pdfBackendApi')>(
      '@/services/pdfBackendApi',
    );

    expect(actualPdfBackendApi.classifyOcrExecutionProbeError({
      code: 'ECONNABORTED',
      isAxiosError: true,
    })).toEqual(expect.objectContaining({
      category: 'network',
      title: 'OCR 执行连接失败',
    }));
  });

  it('uses the visibly selected OCR credential when checking the remote engine', async () => {
    const credential = makeOcrCredential();
    vi.mocked(credentialsApi.listCredentials).mockResolvedValue([credential]);

    window.history.replaceState(null, '', buildSettingsSectionPath('ocr'));
    render(<SettingsPage />);

    await screen.findByRole('heading', { name: 'OCR 设置' });
    fireEvent.change(screen.getByLabelText('OCR 策略'), { target: { value: 'engine' } });
    fireEvent.change(screen.getByLabelText('选择引擎'), { target: { value: 'remote_api' } });

    const credentialPicker = await screen.findByLabelText('已保存 API');
    await waitFor(() => expect(credentialPicker).toHaveValue(credential.credential_id));
    fireEvent.click(screen.getByRole('button', { name: '检查当前引擎' }));

    await waitFor(() => expect(pdfBackendApi.checkOcrHealth).toHaveBeenCalled());
    const calls = vi.mocked(pdfBackendApi.checkOcrHealth).mock.calls;
    const payload = calls[calls.length - 1]?.[0];
    expect(payload?.engine_config).toEqual(expect.objectContaining({
      credential_id: credential.credential_id,
    }));
    expect(payload?.engine_config).not.toHaveProperty('api_key');
  });

  it('keeps an applied OCR credential reference in health checks without exposing its API key', async () => {
    const credential = makeOcrCredential();
    const initialStatus: Awaited<ReturnType<typeof pdfBackendApi.fetchOcrStatus>> = {
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
          available: true,
          requires_network: true,
          unavailable_reason: null,
          readiness_status: 'ready',
          readiness_blockers: [],
          next_safe_local_actions: [],
        },
      ],
      warning: null,
      next_safe_local_actions: [],
    };
    const appliedStatus: Awaited<ReturnType<typeof pdfBackendApi.fetchOcrStatus>> = {
      ...initialStatus,
      policy: 'engine',
      configured_engine: 'remote_api',
      selected_engine: 'remote_api',
      source: 'config',
      engine_config: {
        credential_id: credential.credential_id,
        provider: 'mistral',
        base_url: credential.base_url,
        endpoint_path: '/ocr',
        model: credential.model,
        allow_remote_upload: true,
        allow_insecure_http: false,
        timeout_seconds: 120,
      },
    };
    vi.mocked(credentialsApi.listCredentials)
      .mockResolvedValueOnce([credential])
      .mockResolvedValueOnce([credential]);
    vi.mocked(pdfBackendApi.fetchOcrStatus)
      .mockResolvedValueOnce(initialStatus)
      .mockResolvedValueOnce(appliedStatus);

    window.history.replaceState(null, '', buildSettingsSectionPath('ocr'));
    render(<SettingsPage />);

    await screen.findByRole('heading', { name: 'OCR 设置' });
    fireEvent.change(screen.getByLabelText('OCR 策略'), { target: { value: 'engine' } });
    fireEvent.change(screen.getByLabelText('选择引擎'), { target: { value: 'remote_api' } });

    const credentialPicker = await screen.findByLabelText('已保存 API');
    await waitFor(() => expect(credentialPicker).toHaveValue(credential.credential_id));
    fireEvent.click(screen.getByRole('button', { name: '应用' }));

    await waitFor(() => {
      expect(credentialsApi.applyCredentialToSubsystem).toHaveBeenCalledWith('ocr', credential.credential_id);
      expect(screen.getByRole('button', { name: '检查当前引擎' })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole('button', { name: '检查当前引擎' }));

    await waitFor(() => expect(pdfBackendApi.checkOcrHealth).toHaveBeenCalled());
    const calls = vi.mocked(pdfBackendApi.checkOcrHealth).mock.calls;
    const payload = calls[calls.length - 1]?.[0];
    expect(payload).toBeDefined();
    expect(payload?.engine).toBe('remote_api');
    expect(payload?.engine_config).toEqual(expect.objectContaining({
      credential_id: credential.credential_id,
    }));
    expect(payload?.engine_config).not.toHaveProperty('api_key');
  });

  it('keeps an applied PaddleOCR credential on the asynchronous jobs provider', async () => {
    const credential: RuntimeCredentialPublic = {
      ...makeOcrCredential(),
      provider: 'PaddleOCR',
      model: 'PaddleOCR-VL-1.6',
      base_url: 'https://paddleocr.aistudio-app.com',
    };
    const availableEngines: Awaited<ReturnType<typeof pdfBackendApi.fetchOcrStatus>>['available_engines'] = [
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
        available: true,
        requires_network: true,
        unavailable_reason: null,
        readiness_status: 'ready',
        readiness_blockers: [],
        next_safe_local_actions: [],
      },
    ];
    vi.mocked(credentialsApi.listCredentials).mockResolvedValue([credential]);
    vi.mocked(pdfBackendApi.fetchOcrStatus)
      .mockResolvedValueOnce({
        policy: 'auto',
        configured_engine: null,
        selected_engine: 'rapidocr',
        language: 'zh',
        source: 'default',
        engine_config: {},
        available_engines: availableEngines,
        warning: null,
        next_safe_local_actions: [],
      })
      .mockResolvedValueOnce({
        policy: 'engine',
        configured_engine: 'remote_api',
        selected_engine: 'remote_api',
        language: 'zh',
        source: 'config',
        engine_config: {
          credential_id: credential.credential_id,
          provider: 'paddle_jobs',
          base_url: credential.base_url,
          model: credential.model,
          allow_remote_upload: true,
          allow_insecure_http: false,
          timeout_seconds: 60,
        },
        available_engines: availableEngines,
        warning: null,
        next_safe_local_actions: [],
      });

    window.history.replaceState(null, '', buildSettingsSectionPath('ocr'));
    render(<SettingsPage />);

    await screen.findByRole('heading', { name: 'OCR 设置' });
    fireEvent.change(screen.getByLabelText('OCR 策略'), { target: { value: 'engine' } });
    fireEvent.change(screen.getByLabelText('选择引擎'), { target: { value: 'remote_api' } });
    const credentialPicker = await screen.findByLabelText('已保存 API');
    await waitFor(() => expect(credentialPicker).toHaveValue(credential.credential_id));
    fireEvent.click(screen.getByRole('button', { name: '应用' }));

    await waitFor(() => expect(screen.getByLabelText('服务类型')).toHaveValue('paddle_jobs'));
    fireEvent.click(screen.getByRole('button', { name: '检查当前引擎' }));

    await waitFor(() => expect(pdfBackendApi.checkOcrHealth).toHaveBeenCalled());
    const calls = vi.mocked(pdfBackendApi.checkOcrHealth).mock.calls;
    const payload = calls[calls.length - 1]?.[0];
    expect(payload?.engine_config).toEqual(expect.objectContaining({
      credential_id: credential.credential_id,
      provider: 'paddle_jobs',
      base_url: credential.base_url,
      model: credential.model,
    }));
    expect(payload?.engine_config).not.toHaveProperty('api_key');
    expect(payload?.engine_config).not.toHaveProperty('endpoint_path');

    fireEvent.click(screen.getByRole('button', { name: '保存 OCR 设置' }));
    await waitFor(() => expect(pdfBackendApi.saveOcrEngineSelection).toHaveBeenCalled());
    const saveCalls = vi.mocked(pdfBackendApi.saveOcrEngineSelection).mock.calls;
    const savePayload = saveCalls[saveCalls.length - 1]?.[0];
    expect(savePayload).toEqual(expect.objectContaining({
      policy: 'engine',
      engine: 'remote_api',
      language: 'zh',
      engine_config: expect.objectContaining({
        credential_id: credential.credential_id,
        provider: 'paddle_jobs',
        base_url: credential.base_url,
        model: credential.model,
      }),
    }));
    expect(savePayload?.engine_config).not.toHaveProperty('api_key');
    expect(savePayload?.engine_config).not.toHaveProperty('endpoint_path');
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
    expect(screen.getByLabelText('模型上下文窗口')).toHaveValue(258400);
    expect(screen.getByLabelText('模型上下文窗口')).toHaveAttribute('max', '2000000');
    expect(screen.getByLabelText('自动整理触发长度')).toHaveValue(150000);
    expect(screen.getByLabelText('自动整理触发长度')).toHaveAttribute('max', '1000000');
    expect(screen.getByLabelText('工具输出总上限')).toHaveValue(8000);
    expect(screen.getByLabelText('工具输出总上限')).toHaveAttribute('max', '32000');
    expect(screen.getByLabelText('整理后的摘要长度')).toHaveAttribute('max', '16000');
    expect(screen.getByLabelText('最近对话保留轮数')).toHaveAttribute('max', '20');
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

    fireEvent.click(await screen.findByRole('button', { name: '新增' }));
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

  it('describes OCR credential validation as a configuration check, not a connection test', async () => {
    vi.mocked(credentialsApi.listCredentials).mockResolvedValueOnce([makeOcrCredential()]);

    render(<CredentialsSection />);

    fireEvent.click(await screen.findByRole('button', { name: '测试 Mistral mistral-ocr-latest' }));

    expect(await screen.findAllByText('配置检查通过 · 配置完整')).toHaveLength(2);
    expect(screen.queryByText(/连接测试通过/)).not.toBeInTheDocument();
  });
});
