import type { CitationAnchor } from '@/types/writing';

const CITE_PREFIX = 'cite';
const CITATION_TOKEN_PATTERN = /\[\^([^\]]+)\]/g;

const createShortId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().split('-')[0];
  }

  return Math.random().toString(36).slice(2, 8);
};

export const createCitationAnchorId = (materialId?: string | null) => {
  const normalizedMaterialId = (materialId || 'unbound')
    .toString()
    .trim()
    .replace(/[^a-z0-9_-]+/gi, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '') || 'unbound';

  return `${CITE_PREFIX}:${normalizedMaterialId}:${createShortId()}`;
};

export const createCitationToken = (anchorId: string) => `[^${anchorId}]`;

export const parseCitationMaterialId = (anchorId: string): string | null => {
  const match = anchorId.match(/^cite:(.+):([a-z0-9-]+)$/i);

  if (!match) {
    return null;
  }

  const materialId = match[1]?.trim();
  return materialId && materialId !== 'unbound' ? materialId : null;
};

export const parseCitationAnchors = (content: string): CitationAnchor[] => {
  const anchors: CitationAnchor[] = [];
  let match: RegExpExecArray | null;
  let ordinal = 0;

  CITATION_TOKEN_PATTERN.lastIndex = 0;

  while ((match = CITATION_TOKEN_PATTERN.exec(content)) !== null) {
    ordinal += 1;
    const anchorId = match[1];

    anchors.push({
      id: anchorId,
      materialId: parseCitationMaterialId(anchorId),
      token: match[0],
      startOffset: match.index,
      endOffset: match.index + match[0].length,
      ordinal,
    });
  }

  return anchors;
};

export const findCitationAnchorRange = (content: string, anchorId: string) => {
  const token = createCitationToken(anchorId);
  const startOffset = content.indexOf(token);

  if (startOffset < 0) {
    return null;
  }

  return {
    startOffset,
    endOffset: startOffset + token.length,
  };
};

export const getCitationAnchorLabel = (anchor: CitationAnchor) => {
  const materialSegment = anchor.materialId ? ` · ${anchor.materialId}` : ' · 未绑定';
  return `引用 ${anchor.ordinal}${materialSegment}`;
};