import { useEffect, useMemo, useRef } from 'react';
import { useEditor, EditorContent, type Editor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Placeholder } from '@tiptap/extension-placeholder';
import { Markdown, type MarkdownStorage } from 'tiptap-markdown';
import {
  Bold, Italic, Strikethrough, Heading1, Heading2, Heading3,
  List, ListOrdered, Undo, Redo,
} from 'lucide-react';
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
import { CitationNode, CITATION_NODE_NAME } from './citationNode';

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

function getMarkdown(editor: Editor): string {
  return (editor.storage as unknown as { markdown: MarkdownStorage }).markdown.getMarkdown();
}

function MenuBar({ editor }: { editor: Editor | null }) {
  if (!editor) return null;
  const btn = (active: boolean) =>
    cn(
      'p-1.5 rounded transition-colors',
      active ? 'bg-primary/15 text-primary' : 'text-foreground/40 hover:bg-surface-container hover:text-foreground/70',
    );
  return (
    <div className="sticky top-0 z-10 -mx-10 -mt-8 mb-6 flex flex-wrap items-center gap-0.5 border-b border-outline-variant bg-surface-low px-4 py-2">
      <button type="button" onClick={() => editor.chain().focus().toggleBold().run()} className={btn(editor.isActive('bold'))} title="Bold"><Bold size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleItalic().run()} className={btn(editor.isActive('italic'))} title="Italic"><Italic size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleStrike().run()} className={btn(editor.isActive('strike'))} title="Strikethrough"><Strikethrough size={15} /></button>
      <span className="mx-1 h-5 w-px bg-outline-variant/50" />
      <button type="button" onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} className={btn(editor.isActive('heading', { level: 1 }))} title="H1"><Heading1 size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} className={btn(editor.isActive('heading', { level: 2 }))} title="H2"><Heading2 size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} className={btn(editor.isActive('heading', { level: 3 }))} title="H3"><Heading3 size={15} /></button>
      <span className="mx-1 h-5 w-px bg-outline-variant/50" />
      <button type="button" onClick={() => editor.chain().focus().toggleBulletList().run()} className={btn(editor.isActive('bulletList'))} title="Bullet List"><List size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleOrderedList().run()} className={btn(editor.isActive('orderedList'))} title="Ordered List"><ListOrdered size={15} /></button>
      <span className="mx-1 h-5 w-px bg-outline-variant/50" />
      <button type="button" onClick={() => editor.chain().focus().undo().run()} className={btn(false)} title="Undo"><Undo size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().redo().run()} className={btn(false)} title="Redo"><Redo size={15} /></button>
    </div>
  );
}

/**
 * Rich (WYSIWYG) view over the canonical manuscript markdown string. Standard
 * formatting (headings / bold / italic / lists) round-trips through
 * tiptap-markdown; citation tokens `[^cite:mat:id]` render as inline `[n]`
 * superscript nodes. The editor serializes back to the same markdown string on
 * every edit, so save / export / anchor parsing keep operating on it unchanged.
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

  // Latest props in refs so the editor instance is created once while callbacks
  // always read fresh data (no stale closures, no re-instantiation).
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
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      Placeholder.configure({ placeholder: placeholder || '' }),
      Markdown.configure({ html: false, transformPastedText: true, transformCopiedText: true }),
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
    content,
    editorProps: {
      attributes: {
        class: cn(
          'prose prose-sm sm:prose-base max-w-none font-doc leading-loose focus:outline-none min-h-[68vh]',
          'text-gray-800 dark:text-foreground',
        ),
      },
    },
    onUpdate: ({ editor: instance }) => {
      if (applyingExternalRef.current) return;
      const text = getMarkdown(instance);
      if (text === lastSerializedRef.current) return;
      lastSerializedRef.current = text;
      onChangeRef.current(text);
    },
  });

  // Sync external content changes (section switch, apply-rewrite, spark insert)
  // into the editor without clobbering in-progress edits.
  useEffect(() => {
    if (!editor) return;
    const current = getMarkdown(editor);
    if (content === current) return;
    applyingExternalRef.current = true;
    editor.commands.setContent(content);
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

    const nextContent = getMarkdown(editor);
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

  return (
    <div className={className}>
      <MenuBar editor={editor} />
      <EditorContent editor={editor} />
    </div>
  );
}
