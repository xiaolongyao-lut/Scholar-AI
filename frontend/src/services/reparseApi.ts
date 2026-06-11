/**
 * A16b reparse-with-marker API client.
 *
 * Backend: POST /resources/projects/{project_id}/reparse-with-marker
 * Defined in literature_assistant/core/routers/resources_router/endpoints_search_upload.py
 */
import { getApiBaseUrl } from './apiBaseUrl';

export interface ReparseSuccess {
  material_id: string;
  title: string;
  chunks: number;
  sidecar_markdown_path: string;
  has_blocks: boolean;
  has_markdown_full: boolean;
}

export interface ReparseSkip {
  material_id: string;
  title: string;
  reason: 'source_missing' | 'not_pdf' | string;
}

export interface ReparseFailure {
  material_id: string;
  title: string;
  error: string;
}

export interface ReparseResult {
  project_id: string;
  backend: string;
  reparsed_count: number;
  skipped_count: number;
  failed_count: number;
  reparsed: ReparseSuccess[];
  skipped: ReparseSkip[];
  failed: ReparseFailure[];
}

export async function reparseProjectWithMarker(
  projectId: string,
): Promise<ReparseResult> {
  const encoded = encodeURIComponent(projectId);
  const response = await fetch(
    `${getApiBaseUrl()}/resources/projects/${encoded}/reparse-with-marker`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    },
  );
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(
      `reparse failed: ${response.status} ${response.statusText} ${text}`,
    );
  }
  return (await response.json()) as ReparseResult;
}
