export const PDF_URL_BBOX_UNIT = 'normalized_ratio' as const;

export type PdfBboxUnit =
  | typeof PDF_URL_BBOX_UNIT
  | 'normalized_1000'
  | 'pdf_points'
  | 'css_pixels';

export type PdfBbox = readonly [number, number, number, number];

export interface PdfHighlightRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PdfEvidenceAnchor {
  material_id: string;
  page?: number | null;
  page_label?: string | null;
  chunk_id?: string | null;
  bbox?: PdfBbox | null;
  bbox_unit?: PdfBboxUnit | null;
  selected_text?: string | null;
  source_kind?: string | null;
  source_labels?: readonly string[];
}

const PDF_BBOX_UNITS: ReadonlySet<string> = new Set([
  PDF_URL_BBOX_UNIT,
  'normalized_1000',
  'pdf_points',
  'css_pixels',
]);

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function roundUrlNumber(value: number): string {
  return String(Number(value.toFixed(4)));
}

export function isPdfBboxUnit(value: unknown): value is PdfBboxUnit {
  return typeof value === 'string' && PDF_BBOX_UNITS.has(value);
}

export function readPdfBbox(value: unknown): PdfBbox | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const [a, b, c, d] = value;
  if (![a, b, c, d].every(isFiniteNumber)) return null;
  return [a, b, c, d];
}

export function normalizePdfUrlBbox(
  value: unknown,
  bboxUnit: PdfBboxUnit | null | undefined = PDF_URL_BBOX_UNIT,
): PdfBbox | null {
  if (bboxUnit && bboxUnit !== PDF_URL_BBOX_UNIT) return null;
  const bbox = readPdfBbox(value);
  if (!bbox) return null;
  const [a, b, c, d] = bbox;

  if (
    a >= 0 &&
    b >= 0 &&
    c > 0 &&
    d > 0 &&
    a <= 1 &&
    b <= 1 &&
    a + c <= 1.0001 &&
    b + d <= 1.0001
  ) {
    return [a, b, c, d];
  }

  // Legacy deep links sometimes used normalized corners. Normalize once at the URL boundary.
  if (a >= 0 && b >= 0 && c > a && d > b && c <= 1 && d <= 1) {
    return [a, b, c - a, d - b];
  }

  return null;
}

export function parsePdfBboxSearchParam(value: string | null): PdfBbox | null {
  if (!value) return null;
  const parts = value.split(',').map((part) => Number(part.trim()));
  return normalizePdfUrlBbox(parts);
}

export function toPdfHighlightRect(
  value: unknown,
  bboxUnit: PdfBboxUnit | null | undefined = PDF_URL_BBOX_UNIT,
): PdfHighlightRect | null {
  const bbox = normalizePdfUrlBbox(value, bboxUnit);
  if (!bbox) return null;
  const [x, y, w, h] = bbox;
  return { x, y, w, h };
}

export function encodePdfBboxParam(
  value: unknown,
  bboxUnit: PdfBboxUnit | null | undefined = PDF_URL_BBOX_UNIT,
): string | null {
  const bbox = normalizePdfUrlBbox(value, bboxUnit);
  if (!bbox) return null;
  return bbox.map(roundUrlNumber).join(',');
}
