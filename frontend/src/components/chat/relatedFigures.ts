import type { EvidenceRefLike } from '@/components/evidence/EvidencePill';
import {
  isPdfBboxUnit,
  normalizePdfUrlBbox,
  type PdfBbox,
  type PdfBboxUnit,
} from '@/lib/pdfAnchor';
import type { ChatRelatedFigure } from './MessageRenderer';

function detailValue(ref: EvidenceRefLike, key: string): unknown {
  const detail = ref.figure_candidate_detail;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return undefined;
  return detail[key];
}

function detailString(ref: EvidenceRefLike, key: string): string | null {
  const value = detailValue(ref, key);
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function validPageNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
    ? value
    : null;
}

interface VisualBboxLocator {
  page: number;
  bbox: PdfBbox;
  bbox_unit: PdfBboxUnit;
}

function validVisualBboxLocator(
  pageValue: unknown,
  bboxValue: unknown,
  bboxUnitValue: unknown,
): VisualBboxLocator | null {
  const page = validPageNumber(pageValue);
  if (page === null) return null;
  const bboxUnit = isPdfBboxUnit(bboxUnitValue) ? bboxUnitValue : null;
  if (!bboxUnit) return null;
  const bbox = normalizePdfUrlBbox(bboxValue, bboxUnit);
  return bbox ? { page, bbox, bbox_unit: bboxUnit } : null;
}

function visualBboxLocator(ref: EvidenceRefLike): VisualBboxLocator | null {
  return validVisualBboxLocator(ref.page, ref.bbox, ref.bbox_unit)
    ?? validVisualBboxLocator(
      detailValue(ref, 'page'),
      detailValue(ref, 'bbox'),
      detailValue(ref, 'bbox_unit'),
    );
}

function finiteScore(ref: EvidenceRefLike): number | null {
  return typeof ref.score === 'number' && Number.isFinite(ref.score) ? ref.score : null;
}

function figureKind(ref: EvidenceRefLike, label: string): ChatRelatedFigure['kind'] {
  const kind = detailString(ref, 'kind')?.toLowerCase();
  if (kind === 'table' || /^(?:表|table\b)/i.test(label.trim())) return 'table';
  if (
    kind === 'formula'
    || kind === 'equation'
    || /^(?:(?:equations?|eqs?)\b|公式|方程)/i.test(label.trim())
  ) return 'formula';
  return 'figure';
}

/** Convert display-only visual evidence refs into lazy-rendered chat figures. */
export function relatedFiguresFromEvidenceRefs(
  evidenceRefs: EvidenceRefLike[] | undefined,
): ChatRelatedFigure[] {
  if (!evidenceRefs || evidenceRefs.length === 0) return [];
  const figures: ChatRelatedFigure[] = [];
  const seen = new Set<string>();
  for (const ref of evidenceRefs) {
    const imagePaths = Array.isArray(ref.image_paths)
      ? ref.image_paths.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      : [];
    for (const imagePath of imagePaths) {
      const assetPath = imagePath.trim();
      if (!assetPath || seen.has(assetPath)) continue;
      seen.add(assetPath);
      const candidateId = detailString(ref, 'id') ?? detailString(ref, 'figure_id') ?? ref.figure_candidate;
      const label = detailString(ref, 'label')
        ?? detailString(ref, 'figure_id')
        ?? ref.figure_candidate
        ?? detailString(ref, 'id')
        ?? `图像证据 ${figures.length + 1}`;
      const caption = detailString(ref, 'caption') ?? ref.text ?? ref.quote ?? label;
      const locator = visualBboxLocator(ref);
      const fallbackPage = validPageNumber(ref.page) ?? validPageNumber(detailValue(ref, 'page'));
      figures.push({
        id: `${candidateId ?? ref.chunk_id ?? 'evidence'}:${assetPath}`,
        kind: figureKind(ref, label),
        label,
        caption,
        material_id: String(ref.material_id ?? ''),
        material_title: ref.source_title ?? ref.source ?? null,
        page: locator?.page ?? fallbackPage,
        bbox: locator ? [...locator.bbox] : null,
        bbox_unit: locator?.bbox_unit ?? null,
        quote: ref.quote ?? null,
        chunk_id: ref.chunk_id ?? null,
        anchor_chunk_id: detailString(ref, 'anchor_chunk_id'),
        relevance_score: finiteScore(ref),
        asset_path: assetPath,
        source: 'chunk_image_paths',
      });
    }
  }
  return figures;
}
