import { createCitationToken } from '@/lib/citationAnchors';

/**
 * Lossless bridge between the manuscript draft string and a TipTap/ProseMirror
 * JSON document.
 *
 * Canonical form is the draft string (`draft.content`): paragraphs separated by
 * `\n`, with inline citation tokens `[^cite:mat_id:short]`. The rich editor is
 * a *view* over this string, so the round-trip invariant must hold for every
 * manuscript string:
 *
 *   docToString(stringToDoc(s)) === s
 *
 * This guarantees switching into the rich editor never mutates content the user
 * did not edit, and that save/export/citation-anchor parsing keep operating on
 * the same string they always have.
 */

export const CITATION_NODE_NAME = 'citation';

// Mirrors the token grammar in citationAnchors.ts: `[^<inner>]` where <inner>
// is the citation anchor id (e.g. `cite:mat_x:ab12`).
const CITATION_TOKEN_PATTERN = /\[\^([^\]]+)\]/g;

export interface PmTextNode {
  type: 'text';
  text: string;
}

export interface PmCitationNode {
  type: typeof CITATION_NODE_NAME;
  attrs: { anchorId: string };
}

export type PmInlineNode = PmTextNode | PmCitationNode;

export interface PmParagraphNode {
  type: 'paragraph';
  content?: PmInlineNode[];
}

export interface PmDoc {
  type: 'doc';
  content: PmParagraphNode[];
}

/** Split a single line into text runs + citation atom nodes. */
function lineToInline(line: string): PmInlineNode[] {
  const nodes: PmInlineNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  CITATION_TOKEN_PATTERN.lastIndex = 0;
  while ((match = CITATION_TOKEN_PATTERN.exec(line)) !== null) {
    if (match.index > lastIndex) {
      nodes.push({ type: 'text', text: line.slice(lastIndex, match.index) });
    }
    nodes.push({ type: CITATION_NODE_NAME, attrs: { anchorId: match[1] } });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < line.length) {
    nodes.push({ type: 'text', text: line.slice(lastIndex) });
  }
  return nodes;
}

/**
 * Parse a manuscript string into a ProseMirror JSON doc: one paragraph per line,
 * citation tokens become atom citation nodes. ProseMirror text nodes are never
 * empty, and an empty line becomes an empty paragraph.
 */
export function stringToDoc(content: string): PmDoc {
  const lines = (content ?? '').split('\n');
  const paragraphs: PmParagraphNode[] = lines.map((line) => {
    const inline = lineToInline(line);
    return inline.length > 0 ? { type: 'paragraph', content: inline } : { type: 'paragraph' };
  });
  // A ProseMirror doc must contain at least one block node.
  if (paragraphs.length === 0) {
    paragraphs.push({ type: 'paragraph' });
  }
  return { type: 'doc', content: paragraphs };
}

function inlineToString(content: JsonNodeLike[] | undefined): string {
  if (!content) return '';
  let out = '';
  for (const node of content) {
    if (node.type === CITATION_NODE_NAME) {
      out += createCitationToken(String(node.attrs?.anchorId ?? ''));
    } else if (node.type === 'text') {
      out += node.text ?? '';
    }
  }
  return out;
}

/**
 * Structural shape of a ProseMirror/TipTap JSON node, loose enough to accept the
 * strongly-typed value returned by `editor.getJSON()` without coupling this
 * module to TipTap's generated node types.
 */
export interface JsonNodeLike {
  type?: string;
  text?: string;
  attrs?: Record<string, unknown> | null;
  content?: JsonNodeLike[];
}

/**
 * Serialize a ProseMirror JSON doc (as produced by `editor.getJSON()`) back to
 * the canonical manuscript string. Each top-level block contributes one line.
 */
export function docToString(doc: JsonNodeLike | null | undefined): string {
  const blocks = doc?.content ?? [];
  return blocks.map((block) => inlineToString(block.content)).join('\n');
}
