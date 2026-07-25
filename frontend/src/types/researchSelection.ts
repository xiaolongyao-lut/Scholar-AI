import {
  PDF_URL_BBOX_UNIT,
  isPdfBboxUnit,
  readPdfBbox,
  type PdfBbox,
  type PdfBboxUnit,
  type PdfContentSelection,
  type PdfSelectionKind,
} from '@/lib/pdfAnchor';

export const RESEARCH_SELECTION_SCHEMA_VERSION = 'scholar-ai-research-selection/v1' as const;
export const RESEARCH_SELECTION_MAX_COUNT = 12;

const RESEARCH_SELECTION_KINDS = new Set<PdfSelectionKind>([
  'text',
  'figure',
  'table',
  'formula',
  'region',
]);

export interface ResearchSelection {
  schema_version: typeof RESEARCH_SELECTION_SCHEMA_VERSION;
  selection_id: string;
  turn_id: string;
  group_id: string;
  /** Zero-based order within one user turn. */
  order: number;
  material_id: string;
  kind: PdfSelectionKind;
  page: number;
  bbox?: PdfBbox;
  bbox_unit?: PdfBboxUnit;
  text?: string;
  label?: string;
  chunk_id?: string;
  candidate_id?: string;
}

export interface ResearchSelectionSource {
  selectionId: string;
  materialId: string;
  selection: PdfContentSelection;
}

export interface BuildResearchSelectionsInput {
  turnId: string;
  groupId: string;
  selections: readonly ResearchSelectionSource[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function boundedString(value: unknown, maxLength: number): string | undefined {
  if (typeof value !== 'string') return undefined;
  const normalized = value.trim();
  return normalized ? normalized.slice(0, maxLength) : undefined;
}

function readSelectionKind(value: unknown): PdfSelectionKind | undefined {
  return typeof value === 'string' && RESEARCH_SELECTION_KINDS.has(value as PdfSelectionKind)
    ? value as PdfSelectionKind
    : undefined;
}

function readSelectionBbox(value: unknown, unit: PdfBboxUnit): PdfBbox | undefined {
  const bbox = readPdfBbox(value);
  if (!bbox) return undefined;
  const [x, y, width, height] = bbox;
  if (x < 0 || y < 0 || width <= 0 || height <= 0) return undefined;
  if (
    unit === 'normalized_ratio'
    && (x > 1 || y > 1 || x + width > 1.0001 || y + height > 1.0001)
  ) {
    return undefined;
  }
  if (
    unit === 'normalized_1000'
    && (x > 1000 || y > 1000 || x + width > 1000.1 || y + height > 1000.1)
  ) {
    return undefined;
  }
  return bbox;
}

function sanitizeResearchSelection(value: unknown): ResearchSelection | null {
  if (!isRecord(value)) return null;
  if (
    value.schema_version !== undefined
    && value.schema_version !== RESEARCH_SELECTION_SCHEMA_VERSION
  ) {
    return null;
  }

  const selectionId = boundedString(value.selection_id, 256);
  const turnId = boundedString(value.turn_id, 256);
  const groupId = boundedString(value.group_id, 256);
  const materialId = boundedString(value.material_id, 256);
  const kind = readSelectionKind(value.kind);
  const order = value.order;
  const page = value.page;
  if (
    !selectionId
    || !turnId
    || !groupId
    || !materialId
    || !kind
    || typeof order !== 'number'
    || !Number.isSafeInteger(order)
    || order < 0
    || order >= RESEARCH_SELECTION_MAX_COUNT
    || typeof page !== 'number'
    || !Number.isSafeInteger(page)
    || page < 1
  ) {
    return null;
  }

  const text = boundedString(value.text, 4000);
  const label = boundedString(value.label, 160);
  const chunkId = boundedString(value.chunk_id, 256);
  const candidateId = boundedString(value.candidate_id, 256);
  if (value.bbox_unit !== undefined && !isPdfBboxUnit(value.bbox_unit)) return null;
  const bboxUnit = isPdfBboxUnit(value.bbox_unit) ? value.bbox_unit : PDF_URL_BBOX_UNIT;
  const bbox = readSelectionBbox(value.bbox, bboxUnit);
  if (kind === 'text' ? !text : !bbox) return null;

  return {
    schema_version: RESEARCH_SELECTION_SCHEMA_VERSION,
    selection_id: selectionId,
    turn_id: turnId,
    group_id: groupId,
    order,
    material_id: materialId,
    kind,
    page,
    ...(bbox ? { bbox, bbox_unit: bboxUnit } : {}),
    ...(text ? { text } : {}),
    ...(label ? { label } : {}),
    ...(chunkId ? { chunk_id: chunkId } : {}),
    ...(candidateId ? { candidate_id: candidateId } : {}),
  };
}

/**
 * Validate selections crossing storage or API boundaries.
 *
 * Invalid entries are dropped independently so one malformed legacy message
 * cannot make an otherwise readable conversation unavailable. Request-only
 * image indexes, encoded pixels, asset paths, and all unknown keys are omitted.
 */
export function sanitizeResearchSelections(value: unknown): ResearchSelection[] {
  if (!Array.isArray(value)) return [];
  const selections: ResearchSelection[] = [];
  const selectionIds = new Set<string>();
  const ordersByGroup = new Set<string>();
  for (const item of value.slice(0, RESEARCH_SELECTION_MAX_COUNT)) {
    const selection = sanitizeResearchSelection(item);
    if (!selection || selectionIds.has(selection.selection_id)) continue;
    const groupOrder = `${selection.group_id}:${selection.order}`;
    if (ordersByGroup.has(groupOrder)) continue;
    selectionIds.add(selection.selection_id);
    ordersByGroup.add(groupOrder);
    selections.push(selection);
  }
  return selections.sort((left, right) => left.order - right.order);
}

/** Build one durable, ordered user-turn snapshot from transient PDF selections. */
export function buildResearchSelections(input: BuildResearchSelectionsInput): ResearchSelection[] {
  const turnId = boundedString(input.turnId, 256);
  const groupId = boundedString(input.groupId, 256);
  if (!turnId || !groupId) return [];

  const raw = input.selections.slice(0, RESEARCH_SELECTION_MAX_COUNT).map((source, order) => ({
    schema_version: RESEARCH_SELECTION_SCHEMA_VERSION,
    selection_id: source.selectionId,
    turn_id: turnId,
    group_id: groupId,
    order,
    material_id: source.materialId,
    kind: source.selection.kind,
    page: source.selection.page,
    bbox: source.selection.bbox,
    bbox_unit: source.selection.bbox_unit,
    text: source.selection.text,
    label: source.selection.label,
    chunk_id: source.selection.chunk_id,
    candidate_id: source.selection.candidate_id,
  }));
  return sanitizeResearchSelections(raw);
}
