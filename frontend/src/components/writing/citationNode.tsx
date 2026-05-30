import { useEffect, useReducer } from 'react';
import { Node, mergeAttributes } from '@tiptap/core';
import { ReactNodeViewRenderer, NodeViewWrapper, type NodeViewProps } from '@tiptap/react';
import { cn } from '@/lib/utils';
import { CITATION_NODE_NAME } from './manuscriptSerialization';

export interface CitationNodeOptions {
  /** Human-readable hover label for a citation anchor id (material title / unbound). */
  resolveLabel: (anchorId: string) => string;
  /** Invoked when the user clicks a citation marker (locate / open source). */
  onActivate: (anchorId: string) => void;
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
 * Renders as a clickable `[n]` superscript; serialization back to the token is
 * handled by manuscriptSerialization (the node carries the full anchor id).
 */
export const CitationNode = Node.create<CitationNodeOptions>({
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
