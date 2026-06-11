/**
 * PDF backend status — A16a Settings UI 状态探测.
 *
 * Backend endpoint: GET /api/pdf-backend/status
 * Defined in literature_assistant/core/routers/pdf_backend_router.py
 */
import { getApiBaseUrl } from './apiBaseUrl';

export interface PDFBackendStatus {
  active_backend: 'pymupdf' | 'marker';
  active_source: 'env' | 'feature_flag' | 'default';
  env_var_name: string;
  env_var_value: string | null;
  feature_flag_name: string;
  feature_flag_enabled: boolean;
  marker_installed: boolean;
  marker_version: string | null;
  marker_install_hint: string;
}

export async function fetchPdfBackendStatus(): Promise<PDFBackendStatus> {
  const response = await fetch(`${getApiBaseUrl()}/api/pdf-backend/status`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(
      `PDF backend status fetch failed: ${response.status} ${response.statusText}`,
    );
  }
  return (await response.json()) as PDFBackendStatus;
}
