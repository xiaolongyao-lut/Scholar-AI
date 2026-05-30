import { useEffect, useMemo, useRef } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Placeholder } from '@tiptap/extension-placeholder';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import type {
  CitationAnchor,
  CitationInsertRequest,
  CitationFocusRequest,
  WritingMaterial,
} from '@/types/writing';
import {
  createCitationAnchorId,
  getCitationAnchorInstanceId,
  parseCitationMaterialId,
} from '@/lib/citationAnchors';
import { CitationNode } from './citationNode';
import { CITATION_NODE_NAME, docToString, stringToDoc } from './manuscriptSerialization';

interface ManuscriptEditorProps {
  content: string;
  onChange: (content: string) => void;
  placeholder?: string;
  materials: WritingMaterial[];
  citationAnchors: CitationAnchor[];
  citationInsertRequest: CitationInsertRequest | null;
  citationFocusRequest: CitationFocusRequest | null;
  onCitationInsertHandled: (requestId: string, anchorInstanceId: string, materialId: string | null) => void;
  onCitationFocusHandled: (requestId: string) => void;
  onRequestAnchorFocus: (anchor: CitationAnchor) => void;
  className?: string;
}

/**
 * Rich (WYSIWYG) view over the canonical manuscript string. Citation tokens are
 * rendered as inline `[n]` superscript nodes; everything else is plain
 * paragraph text. The editor never owns the document model — it serializes back
 * to the same `draft.content` string on every edit, so save / export / anchor
 * parsing are unaffected.
 */
export function ManuscriptEditor({
  content,
  onChange,
  placeholder,
  materials,
  citationAnchors,
  citationInsertRequest,
  citationFocusRequest,
  onCitationInsertHandled,
  onCitationFocusHandled,
  onRequestAnchorFocus,
  className,
}: ManuscriptEditorProps) {
  const { t } = useI18n();

  // Latest props kept in refs so the editor instance can be created once while
  // its callbacks always see fresh data (no stale closures, no re-instantiation).
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const anchorsRef = useRef(citationAnchors);
  anchorsRef.current = citationAnchors;
  const onActivateRef = useRef(onRequestAnchorFocus);
  onActivateRef.current = onRequestAnchorFocus;

  const materialTitleById = useMemo(() => {
    const map = new Map<string, string>();
    for (const material of materials) map.set(material.id, material.titleZh);
    return map;
  }, [materials]);
  const materialTitleByIdRef = useRef(materialTitleById);
  materialTitleByIdRef.current = materialTitleById;

  const applyingExternalRef = useRef(false);
  const lastSerializedRef = useRef(content);
  const handledInsertRef = useRef<string | null>(null);
  const handledFocusRef = useRef<string | null>(null);

  const editor = useEditor({
    extensions: [
      // Minimal schema: paragraphs + text + undo only. Marks/blocks that cannot
      // round-trip to the plain manuscript string are disabled so the rich view
      // can never silently drop formatting on serialize.
      StarterKit.configure({
        heading: false,
        bold: false,
        italic: false,
        strike: false,
        code: false,
        codeBlock: false,
        blockquote: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        horizontalRule: false,
        hardBreak: false,
      }),
      Placeholder.configure({ placeholder: placeholder || '' }),
      CitationNode.configure({
        resolveLabel: (anchorId: string) => {
          const materialId = parseCitationMaterialId(anchorId);
          const title = materialId ? materialTitleByIdRef.current.get(materialId) : undefined;
          return title
            ? t('writing.editor.citation_source', { title })
            : t('writing.editor.citation_unbound');
        },
        onActivate: (anchorId: string) => {
          const anchor = anchorsRef.current.find((item) => item.id === anchorId);
          if (anchor) onActivateRef.current(anchor);
        },
      }),
    ],
    content: stringToDoc(content),
    editorProps: {
      attributes: {
        class: cn(
          'font-doc text-base leading-loose focus:outline-none min-h-[72vh]',
          'text-gray-800 dark:text-foreground',
        ),
      },
    },
    onUpdate: ({ editor: instance }) => {
      if (applyingExternalRef.current) return;
      const text = docToString(instance.getJSON());
      if (text === lastSerializedRef.current) return;
      lastSerializedRef.current = text;
      onChangeRef.current(text);
    },
  });

  // Sync external content changes (section switch, apply-rewrite, spark insert)
  // into the editor without clobbering the user's in-progress edits.
  useEffect(() => {
    if (!editor) return;
    const current = docToString(editor.getJSON());
    if (content === current) return;
    applyingExternalRef.current = true;
    editor.commands.setContent(stringToDoc(content));
    applyingExternalRef.current = false;
    lastSerializedRef.current = content;
  }, [content, editor]);

  // Citation insertion requested from the toolbar / reference drawer.
  useEffect(() => {
    const request = citationInsertRequest;
    if (!editor || !request || handledInsertRef.current === request.requestId) return;

    handledInsertRef.current = request.requestId;
    const anchorId = createCitationAnchorId(request.materialId);
    editor.chain().focus().insertCitation(anchorId).run();

    const nextContent = docToString(editor.getJSON());
    const tokenOffset = nextContent.indexOf(`[^${anchorId}]`);
    const instanceId = getCitationAnchorInstanceId(anchorId, tokenOffset >= 0 ? tokenOffset : 0);
    onCitationInsertHandled(request.requestId, instanceId, request.materialId);
  }, [citationInsertRequest, editor, onCitationInsertHandled]);

  // Locate request: select + scroll to the matching citation node.
  useEffect(() => {
    const request = citationFocusRequest;
    if (!editor || !request || handledFocusRef.current === request.requestId) return;

    handledFocusRef.current = request.requestId;
    let targetPos: number | null = null;
    editor.state.doc.descendants((node, pos) => {
      if (targetPos === null && node.type.name === CITATION_NODE_NAME && node.attrs.anchorId === request.anchorId) {
        targetPos = pos;
        return false;
      }
      return true;
    });

    if (targetPos !== null) {
      editor.chain().focus().setNodeSelection(targetPos).scrollIntoView().run();
    }
    onCitationFocusHandled(request.requestId);
  }, [citationFocusRequest, editor, onCitationFocusHandled]);

  return <EditorContent editor={editor} className={className} />;
}
