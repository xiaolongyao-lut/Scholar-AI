import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';

const API_BASE = getApiBaseUrl();

export interface ExportDocxRequest {
  /** TipTap HTML content */
  html: string;
  /** TipTap JSON content (for structured parsing) */
  json: object;
  /** Export title (used as document title) */
  title?: string;
  /** Style profile name or custom profile */
  style_profile?: string;
}

export interface ExportDocxResponse {
  /** Download URL or base64-encoded docx */
  url: string;
  filename: string;
}

export async function exportToDocx(req: ExportDocxRequest): Promise<ExportDocxResponse> {
  const resp = await axios.post(`${API_BASE}/api/export/docx`, req, {
    responseType: 'blob',
  });
  const disposition = resp.headers['content-disposition'];
  const filename = disposition
    ? disposition.split('filename=')[1]?.replace(/"/g, '')
    : 'export.docx';
  const url = URL.createObjectURL(resp.data);
  return { url, filename };
}

export function downloadBlob(url: string, filename: string) {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
