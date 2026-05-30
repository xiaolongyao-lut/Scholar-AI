import { useEffect, useReducer } from 'react';
import { Node, mergeAttributes } from '@tiptap/core';
import { ReactNodeViewRenderer, NodeViewWrapper, type NodeViewProps } from '@tiptap/react';
import type { MarkdownNodeSpec } from 'tiptap-markdown';
import { cn } from '@/lib/utils';

export const CITATION_NODE_NAME = 'citation';

export interface CitationNodeOptions {
  /** Human-readable hover label for a citation anchor id (material title / unbound). */
  resolveLabel: (anchorId: string) => string;
  /** Invoked when the user clicks a citation marker (locate / open source). */
  onActivate: (anchorId: string) => void;
}

export interface CitationNodeStorage {
  markdown: MarkdownNodeSpec;
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    citation: {
      insertCitation: (anchorId: string) => ReturnType;
    };
  }
}

/**
 * 1-based position of the citation node carrying `anchorId` among all citation
 * nodes in document order. Citation anchor ids are unique per insertion
 * (random short id), so this is unambiguous and matches the string-derived
 * ordinals shown in the anchors rail.
 */
function computeOrdinal(editor: NodeViewProps['editor'], anchorId: string): number {
  let ordinal = 0;
  let found = 0;
  editor.state.doc.descendants((node) => {
    if (node.type.name === CITATION_NODE_NAME) {
      ordinal += 1;
      if (node.attrs.anchorId === anchorId) {
        found = ordinal;
        return false;
      }
    }
    return true;
  });
  return found;
}

function CitationNodeView({ node, editor, extension, selected }: NodeViewProps) {
  // Re-render on any document change so the ordinal stays correct when earlier
  // citations are inserted or removed.
  const [, force] = useReducer((tick: number) => tick + 1, 0);
  useEffect(() => {
    const handler = () => force();
    editor.on('update', handler);
    return () => {
      editor.off('update', handler);
    };
  }, [editor]);

  const anchorId = String(node.attrs.anchorId ?? '');
  const options = extension.options as CitationNodeOptions;
  const ordinal = computeOrdinal(editor, anchorId);
  const label = options.resolveLabel(anchorId);

  return (
    <NodeViewWrapper as="span" className="citation-node">
      <sup
        contentEditable={false}
        title={label}
        role="button"
        tabIndex={0}
        aria-label={label}
        onMouseDown={(event) => {
          event.preventDefault();
          options.onActivate(anchorId);
        }}
        className={cn(
          'mx-0.5 inline-flex cursor-pointer select-none items-center rounded-sm px-1 font-label text-[0.72em] font-medium leading-none transition-colors',
          selected
            ? 'bg-primary text-primary-foreground'
            : 'bg-primary/12 text-primary hover:bg-primary/25',
        )}
      >
        [{ordinal || '?'}]
      </sup>
    </NodeViewWrapper>
  );
}

/**
 * Inline atom node representing a manuscript citation token `[^cite:mat:id]`.
 * Renders as a clickable `[n]` superscript. Markdown round-trips via the
 * tiptap-markdown spec below: serialize writes the token verbatim, and a
 * markdown-it inline rule re-emits the token as a `span[data-citation]` element
 * that `parseHTML` reconstructs.
 */
export const CitationNode = Node.create<CitationNodeOptions, CitationNodeStorage>({
  name: CITATION_NODE_NAME,
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  draggable: false,

  addOptions() {
    return {
      resolveLabel: () => '',
      onActivate: () => undefined,
    };
  },

  addStorage() {
    return {
      markdown: {
        serialize(state, node) {
          state.write(`[^${String(node.attrs.anchorId ?? '')}]`);
        },
        parse: {
          setup(markdownit) {
            markdownit.inline.ruler.before('link', CITATION_NODE_NAME, (state, silent) => {
              const src = state.src.slice(state.pos, state.posMax);
              if (src.charCodeAt(0) !== 0x5b /* [ */ || src.charCodeAt(1) !== 0x5e /* ^ */) {
                return false;
              }
              const match = /^\[\^([^\]\s]+)\]/.exec(src);
              if (!match) return false;
              if (!silent) {
                const token = state.push(CITATION_NODE_NAME, '', 0);
                token.markup = match[0];
                token.meta = { anchorId: match[1] };
              }
              state.pos += match[0].length;
              return true;
            });
            markdownit.renderer.rules[CITATION_NODE_NAME] = (tokens, idx) => {
              const anchorId = String(tokens[idx].meta?.anchorId ?? '');
              return `<span data-citation data-anchor-id="${markdownit.utils.escapeHtml(anchorId)}"></span>`;
            };
          },
        },
      },
    };
  },

  addAttributes() {
    return {
      anchorId: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-anchor-id') ?? '',
        renderHTML: (attributes) =>
          attributes.anchorId ? { 'data-anchor-id': attributes.anchorId } : {},
      },
    };
  },

  parseHTML() {
    return [{ tag: 'span[data-citation]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes, { 'data-citation': '' })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(CitationNodeView);
  },

  addCommands() {
    return {
      insertCitation:
        (anchorId: string) =>
        ({ chain }) =>
          chain().insertContent({ type: CITATION_NODE_NAME, attrs: { anchorId } }).run(),
    };
  },
});
