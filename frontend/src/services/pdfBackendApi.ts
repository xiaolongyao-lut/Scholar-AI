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
