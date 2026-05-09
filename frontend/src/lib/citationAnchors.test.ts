import { describe, expect, it } from 'vitest';

import {
  createCitationAnchorId,
  createCitationToken,
  findCitationAnchorRange,
  parseCitationAnchors,
  parseCitationMaterialId,
} from './citationAnchors';

describe('citationAnchors', () => {
  it('creates normalized cite ids and recovers material ids from them', () => {
    const anchorId = createCitationAnchorId('  Paper / 01: Main Finding  ');

    expect(anchorId).toMatch(/^cite:Paper-01-Main-Finding:[a-z0-9]+$/i);
    expect(parseCitationMaterialId(anchorId)).toBe('Paper-01-Main-Finding');
  });

  it('falls back to an unbound id when material id is blank', () => {
    const anchorId = createCitationAnchorId('   ');

    expect(anchorId).toMatch(/^cite:unbound:[a-z0-9]+$/i);
    expect(parseCitationMaterialId(anchorId)).toBeNull();
  });

  it('parses anchor tokens into ordered citation anchors with offsets and material ids', () => {
    const firstToken = '[^cite:paper-1:abc123]';
    const secondToken = '[^cite:unbound:def456]';
    const thirdToken = '[^opaque-anchor]';
    const content = `引文一 ${firstToken} 继续说明 ${secondToken} 最后补一个 ${thirdToken}`;

    const anchors = parseCitationAnchors(content);

    expect(anchors).toEqual([
      {
        id: 'cite:paper-1:abc123',
        instanceId: `cite:paper-1:abc123@${content.indexOf(firstToken)}`,
        materialId: 'paper-1',
        token: firstToken,
        startOffset: content.indexOf(firstToken),
        endOffset: content.indexOf(firstToken) + firstToken.length,
        ordinal: 1,
      },
      {
        id: 'cite:unbound:def456',
        instanceId: `cite:unbound:def456@${content.indexOf(secondToken)}`,
        materialId: null,
        token: secondToken,
        startOffset: content.indexOf(secondToken),
        endOffset: content.indexOf(secondToken) + secondToken.length,
        ordinal: 2,
      },
      {
        id: 'opaque-anchor',
        instanceId: `opaque-anchor@${content.indexOf(thirdToken)}`,
        materialId: null,
        token: thirdToken,
        startOffset: content.indexOf(thirdToken),
        endOffset: content.indexOf(thirdToken) + thirdToken.length,
        ordinal: 3,
      },
    ]);
  });

  it('prefers the requested occurrence when locating repeated anchor tokens', () => {
    const anchorId = 'cite:paper-1:abc123';
    const token = createCitationToken(anchorId);
    const content = `${token} 前文补充 ${token}`;
    const preferredStartOffset = content.lastIndexOf(token);

    expect(findCitationAnchorRange(content, anchorId, preferredStartOffset)).toEqual({
      startOffset: preferredStartOffset,
      endOffset: preferredStartOffset + token.length,
    });

    expect(findCitationAnchorRange(content, anchorId, 999)).toEqual({
      startOffset: 0,
      endOffset: token.length,
    });
  });
});