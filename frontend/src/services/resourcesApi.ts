/**
 * Resources API client — read-only metadata helpers over `/resources/*`.
 *
 * Currently exposes the chunk-page locator endpoint
 * (`GET /resources/chunks/{chunk_id}/locator`) shipped by Track A
 * (commit 95edbb0b). Callers use it to upgrade a `chunk_id`-only
 * evidence pill into a precise PDF deep-link with `&page=<n>`.
 *
 * Design rules:
 * - No throw on 404 / 422 / network: callers fall back to the existing
 *   page=1 deep-link behaviour, so a locator failure must never break
 *   the click.
 * - No backend cache; per-message in-memory cache lives in the caller
 *   (D-CPL-3).
 */
import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import {
  PDF_URL_BBOX_UNIT,
  isPdfBboxUnit,
  readPdfBbox,
  type PdfBbox,
  type PdfBboxUnit,
} from '@/lib/pdfAnchor';

export interface ChunkLocator {
  material_id: string;
  chunk_id: string;
  page: number | null;
  chunk_index: number | null;
  bbox?: PdfBbox | null;
  bbox_unit?: PdfBboxUnit | null;
}

function parseLocator(value: unknown): ChunkLocator | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null;
  }
  const obj = value as Record<string, unknown>;
  if (typeof obj.material_id !== 'string' || obj.material_id.length === 0) return null;
  if (typeof obj.chunk_id !== 'string' || obj.chunk_id.length === 0) return null;
  if (obj.page !== null && (typeof obj.page !== 'number' || !Number.isFinite(obj.page))) {
    return null;
  }
  if (
    obj.chunk_index !== null &&
    (typeof obj.chunk_index !== 'number' || !Number.isFinite(obj.chunk_index))
  ) {
    return null;
  }
  const hasBbox = Object.prototype.hasOwnProperty.call(obj, 'bbox');
  const bbox = hasBbox && obj.bbox !== null ? readPdfBbox(obj.bbox) : null;
  if (hasBbox && obj.bbox !== null && bbox === null) {
    return null;
  }
  const hasBboxUnit = Object.prototype.hasOwnProperty.call(obj, 'bbox_unit');
  const bboxUnit = hasBboxUnit && obj.bbox_unit !== null
    ? (isPdfBboxUnit(obj.bbox_unit) ? obj.bbox_unit : null)
    : bbox
      ? PDF_URL_BBOX_UNIT
      : null;
  if (hasBboxUnit && obj.bbox_unit !== null && bboxUnit === null) {
    return null;
  }
  return {
    material_id: obj.material_id,
    chunk_id: obj.chunk_id,
    page: obj.page,
    chunk_index: obj.chunk_index,
    ...(hasBbox ? { bbox } : {}),
    ...(bbox ? { bbox_unit: bboxUnit ?? PDF_URL_BBOX_UNIT } : hasBboxUnit ? { bbox_unit: null } : {}),
  };
}

/**
 * Resolve a chunk_id to {material_id, chunk_id, page, chunk_index}.
 *
 * Returns:
 *  - ChunkLocator on 200 with a parseable shape.
 *  - null on 404 (unknown chunk_id), 422 (missing/blank project_id),
 *    network error, or unparseable response.
 *
 * Inputs:
 *  - chunkId: required, non-empty.
 *  - projectId: required by the backend (D-CPL-1 amendment); blank or
 *    missing produces a 422 which collapses to null here.
 */
export async function locateChunk(
  chunkId: string,
  projectId: string | null | undefined,
): Promise<ChunkLocator | null> {
  if (typeof chunkId !== 'string' || chunkId.length === 0) {
    return null;
  }
  if (typeof projectId !== 'string' || projectId.length === 0) {
    // Backend would 422 on blank project_id; short-circuit to save a round trip.
    return null;
  }
  try {
    const url = `${getApiBaseUrl()}/resources/chunks/${encodeURIComponent(chunkId)}/locator`;
    const { data } = await axios.get<unknown>(url, {
      params: { project_id: projectId },
      timeout: 5000,
    });
    return parseLocator(data);
  } catch {
    return null;
  }
}
