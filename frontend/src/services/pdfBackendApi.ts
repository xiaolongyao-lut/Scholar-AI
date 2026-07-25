/**
 * PDF and OCR backend status used by Settings.
 *
 * Backend endpoints are defined in
 * literature_assistant/core/routers/pdf_backend_router.py.
 */
import { createDefaultApiClient } from './httpClient';

export interface PDFBackendStatus {
  active_backend: string;
  active_source: string;
  env_var_name: string;
  env_var_value: string | null;
  external_backends_supported: boolean;
  install_hint: string;
  feature_flag_name: string;
  feature_flag_enabled: boolean;
  marker_installed: boolean;
  marker_version: string | null;
  marker_install_hint: string;
  ocr_policy: OcrPolicy;
  ocr_configured_engine: string | null;
  ocr_selected_engine: string | null;
  ocr_language: string;
  ocr_config_source: string;
  ocr_warning: string | null;
}

export type OcrPolicy = 'auto' | 'none' | 'engine';
export type OcrReadinessStatus =
  | 'ready'
  | 'dependency_missing'
  | 'configuration_required'
  | 'adapter_not_wired'
  | 'platform_unsupported'
  | 'unavailable';

export interface OcrEnginePublicInfo {
  name: string;
  display_name: string;
  engine_type: 'local' | 'remote';
  available: boolean;
  requires_network: boolean;
  unavailable_reason: string | null;
  readiness_status: OcrReadinessStatus;
  readiness_blockers: string[];
  next_safe_local_actions: string[];
}

export interface OcrStatusResponse {
  policy: OcrPolicy;
  configured_engine: string | null;
  selected_engine: string | null;
  language: string;
  source: string;
  engine_config: Record<string, unknown>;
  available_engines: OcrEnginePublicInfo[];
  warning: string | null;
  next_safe_local_actions: string[];
}

export interface OcrEngineSelectionRequest {
  policy: OcrPolicy;
  engine?: string | null;
  language: string;
  engine_config: Record<string, unknown>;
}

export interface OcrEngineSelectionResponse {
  saved: boolean;
  config_path: string;
  status: OcrStatusResponse;
}

export interface OcrHealthRequest {
  engine?: string | null;
  engine_config: Record<string, unknown>;
}

export interface OcrHealthResponse {
  ok: boolean;
  detail: string;
  engine: string;
  latency_ms: number | null;
  readiness_status: OcrReadinessStatus;
  readiness_blockers: string[];
  next_safe_local_actions: string[];
}

export interface OcrExecutionRegionSample {
  block_type: string;
  text_preview: string;
  bbox: [number, number, number, number];
}

export interface OcrExecutionProbeRequest {
  confirm_execution: true;
  image_base64?: string;
  image_path?: string;
  engine?: string | null;
  engine_config: Record<string, unknown>;
  language: string;
  preview_chars?: number;
}

export interface OcrExecutionProbeResponse {
  schema_version: 'scholar-ai-ocr-execution-probe/v1';
  confirmed: true;
  engine: string;
  engine_type: 'local' | 'remote';
  requires_network: boolean;
  language: string;
  input_kind: 'image_base64' | 'image_path';
  input_bytes: number;
  input_sha256: string;
  text_length: number;
  text_sha256: string;
  text_preview: string;
  duration_ms: number;
  region_count: number;
  region_samples: OcrExecutionRegionSample[];
}

export type OcrExecutionFailureCategory =
  | 'blocked'
  | 'request'
  | 'provider'
  | 'network'
  | 'contract'
  | 'unexpected';

export interface OcrExecutionFailure {
  category: OcrExecutionFailureCategory;
  title: string;
  detail: string;
}

export class OcrExecutionContractError extends Error {
  public constructor(message: string) {
    super(message);
    this.name = 'OcrExecutionContractError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readRequiredString(
  value: Record<string, unknown>,
  field: string,
  maximumLength: number,
  allowEmpty = false,
): string {
  const candidate = value[field];
  if (
    typeof candidate !== 'string'
    || (!allowEmpty && candidate.trim().length === 0)
    || candidate.length > maximumLength
  ) {
    throw new OcrExecutionContractError(`${field} is invalid in the OCR execution response.`);
  }
  return candidate;
}

function readNonNegativeInteger(value: Record<string, unknown>, field: string): number {
  const candidate = value[field];
  if (typeof candidate !== 'number' || !Number.isInteger(candidate) || candidate < 0) {
    throw new OcrExecutionContractError(`${field} is invalid in the OCR execution response.`);
  }
  return candidate;
}

function readSha256(value: Record<string, unknown>, field: string): string {
  const candidate = readRequiredString(value, field, 64);
  if (!/^[a-f0-9]{64}$/i.test(candidate)) {
    throw new OcrExecutionContractError(`${field} is invalid in the OCR execution response.`);
  }
  return candidate;
}

function parseOcrRegionSample(value: unknown, index: number): OcrExecutionRegionSample {
  if (!isRecord(value)) {
    throw new OcrExecutionContractError(`region_samples.${index} is invalid in the OCR execution response.`);
  }
  const rawBbox = value.bbox;
  if (
    !Array.isArray(rawBbox)
    || rawBbox.length !== 4
    || rawBbox.some((coordinate) => (
      typeof coordinate !== 'number'
      || !Number.isFinite(coordinate)
      || coordinate < 0
      || coordinate > 1
    ))
  ) {
    throw new OcrExecutionContractError(`region_samples.${index}.bbox is invalid in the OCR execution response.`);
  }
  return {
    block_type: readRequiredString(value, 'block_type', 64),
    text_preview: readRequiredString(value, 'text_preview', 120, true),
    bbox: [rawBbox[0], rawBbox[1], rawBbox[2], rawBbox[3]],
  };
}

/** Validate the bounded execution receipt returned by the OCR probe endpoint. */
export function parseOcrExecutionProbeResponse(value: unknown): OcrExecutionProbeResponse {
  if (!isRecord(value)) {
    throw new OcrExecutionContractError('OCR execution response must be an object.');
  }
  if (value.schema_version !== 'scholar-ai-ocr-execution-probe/v1') {
    throw new OcrExecutionContractError('schema_version is invalid in the OCR execution response.');
  }
  if (value.confirmed !== true) {
    throw new OcrExecutionContractError('confirmed is invalid in the OCR execution response.');
  }
  if (value.engine_type !== 'local' && value.engine_type !== 'remote') {
    throw new OcrExecutionContractError('engine_type is invalid in the OCR execution response.');
  }
  if (typeof value.requires_network !== 'boolean') {
    throw new OcrExecutionContractError('requires_network is invalid in the OCR execution response.');
  }
  if (value.input_kind !== 'image_base64' && value.input_kind !== 'image_path') {
    throw new OcrExecutionContractError('input_kind is invalid in the OCR execution response.');
  }
  const rawSamples = value.region_samples;
  if (!Array.isArray(rawSamples) || rawSamples.length > 5) {
    throw new OcrExecutionContractError('region_samples is invalid in the OCR execution response.');
  }
  const regionCount = readNonNegativeInteger(value, 'region_count');
  if (rawSamples.length > regionCount) {
    throw new OcrExecutionContractError('region_samples exceeds region_count in the OCR execution response.');
  }
  return {
    schema_version: 'scholar-ai-ocr-execution-probe/v1',
    confirmed: true,
    engine: readRequiredString(value, 'engine', 128),
    engine_type: value.engine_type,
    requires_network: value.requires_network,
    language: readRequiredString(value, 'language', 32),
    input_kind: value.input_kind,
    input_bytes: readNonNegativeInteger(value, 'input_bytes'),
    input_sha256: readSha256(value, 'input_sha256'),
    text_length: readNonNegativeInteger(value, 'text_length'),
    text_sha256: readSha256(value, 'text_sha256'),
    text_preview: readRequiredString(value, 'text_preview', 1000, true),
    duration_ms: readNonNegativeInteger(value, 'duration_ms'),
    region_count: regionCount,
    region_samples: rawSamples.map(parseOcrRegionSample),
  };
}

function readExecutionErrorStatus(error: unknown): number | null | undefined {
  if (!isRecord(error)) {
    return undefined;
  }
  if (Object.prototype.hasOwnProperty.call(error, 'status')) {
    return typeof error.status === 'number' ? error.status : null;
  }
  if (
    isRecord(error.response)
    && Object.prototype.hasOwnProperty.call(error.response, 'status')
  ) {
    return typeof error.response.status === 'number' ? error.response.status : null;
  }
  return error.isAxiosError === true ? null : undefined;
}

/** Convert transport/protocol failures into stable, non-sensitive UI categories. */
export function classifyOcrExecutionProbeError(error: unknown): OcrExecutionFailure {
  if (error instanceof OcrExecutionContractError) {
    return {
      category: 'contract',
      title: 'OCR 回执格式异常',
      detail: 'OCR 已返回响应，但回执字段不完整或超出安全边界。请更新后端后重试。',
    };
  }
  const status = readExecutionErrorStatus(error);
  if (status === 409) {
    return {
      category: 'blocked',
      title: 'OCR 执行受阻',
      detail: '当前引擎尚未达到执行条件，请先保存设置并完成配置检查。',
    };
  }
  if (status === 400 || status === 404 || status === 405 || status === 422) {
    return {
      category: 'request',
      title: 'OCR 测试请求无效',
      detail: '一次性测试图或当前 OCR 参数未通过后端校验，请刷新状态后重试。',
    };
  }
  if (status === 401 || status === 403 || status === 429 || (typeof status === 'number' && status >= 500)) {
    return {
      category: 'provider',
      title: 'OCR 服务执行失败',
      detail: '请求已进入真实 OCR 执行链路，但服务端未完成识别。请检查凭证、配额和模型设置。',
    };
  }
  if (status === null || status === 408) {
    return {
      category: 'network',
      title: 'OCR 执行连接失败',
      detail: 'OCR 执行请求未能完成，请检查网络、代理规则和服务可达性后重试。',
    };
  }
  return {
    category: 'unexpected',
    title: 'OCR 执行失败',
    detail: '未能完成本次 OCR 执行测试，请稍后重试。',
  };
}

export async function fetchPdfBackendStatus(): Promise<PDFBackendStatus> {
  const response = await createDefaultApiClient().get<PDFBackendStatus>('/api/pdf-backend/status');
  return response.data;
}

export async function fetchOcrStatus(): Promise<OcrStatusResponse> {
  const response = await createDefaultApiClient().get<OcrStatusResponse>('/api/pdf-backend/ocr-status');
  return response.data;
}

export async function saveOcrEngineSelection(
  payload: OcrEngineSelectionRequest,
): Promise<OcrEngineSelectionResponse> {
  const response = await createDefaultApiClient({ timeoutMs: 60_000 })
    .post<OcrEngineSelectionResponse>('/api/pdf-backend/ocr-engine', payload);
  return response.data;
}

export async function checkOcrHealth(payload: OcrHealthRequest): Promise<OcrHealthResponse> {
  const response = await createDefaultApiClient({ timeoutMs: 60_000 })
    .post<OcrHealthResponse>('/api/pdf-backend/ocr-health', payload);
  return response.data;
}

export async function runOcrExecutionProbe(
  payload: OcrExecutionProbeRequest,
): Promise<OcrExecutionProbeResponse> {
  const response = await createDefaultApiClient({ timeoutMs: 620_000 })
    .post<unknown>('/api/pdf-backend/ocr-execution-probe', payload);
  return parseOcrExecutionProbeResponse(response.data);
}
