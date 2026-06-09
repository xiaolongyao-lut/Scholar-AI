import { useEffect, useMemo, useRef } from 'react';
import { useEditor, EditorContent, type Editor } from '@tiptap/react';
import { Fragment, Slice } from '@tiptap/pm/model';
import type { EditorView } from '@tiptap/pm/view';
import StarterKit from '@tiptap/starter-kit';
import { Placeholder } from '@tiptap/extension-placeholder';
import { Underline } from '@tiptap/extension-underline';
import { TextAlign } from '@tiptap/extension-text-align';
import { Image } from '@tiptap/extension-image';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { TextStyleKit } from '@tiptap/extension-text-style';
import { Highlight } from '@tiptap/extension-highlight';
import { Superscript } from '@tiptap/extension-superscript';
import { Subscript } from '@tiptap/extension-subscript';
import { Markdown, type MarkdownStorage } from 'tiptap-markdown';
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Code2,
  Eraser,
  ImagePlus,
  Italic,
  List,
  ListOrdered,
  Minus,
  Quote,
  Redo,
  Strikethrough,
  Subscript as SubscriptIcon,
  Superscript as SuperscriptIcon,
  Underline as UnderlineIcon,
  Undo,
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

interface SelectOption {
  label: string;
  value: string;
}

const FONT_FAMILIES: SelectOption[] = [
  { label: '默认字体', value: '' },
  { label: '宋体', value: 'SimSun, "Songti SC", serif' },
  { label: '黑体', value: 'SimHei, "Heiti SC", sans-serif' },
  { label: '楷体', value: 'KaiTi, "Kaiti SC", serif' },
  { label: '微软雅黑', value: '"Microsoft YaHei", sans-serif' },
  { label: 'Times New Roman', value: '"Times New Roman", Times, serif' },
  { label: 'Arial', value: 'Arial, Helvetica, sans-serif' },
  { label: 'Consolas', value: 'Consolas, "Courier New", monospace' },
];

const FONT_SIZES: SelectOption[] = [
  { label: '10', value: '10pt' },
  { label: '11', value: '11pt' },
  { label: '12', value: '12pt' },
  { label: '14', value: '14pt' },
  { label: '16', value: '16pt' },
  { label: '18', value: '18pt' },
  { label: '24', value: '24pt' },
  { label: '32', value: '32pt' },
];

const LINE_HEIGHTS: SelectOption[] = [
  { label: '单倍', value: '1' },
  { label: '1.15', value: '1.15' },
  { label: '1.5', value: '1.5' },
  { label: '2 倍', value: '2' },
];

const TEXT_COLORS: SelectOption[] = [
  { label: '自动', value: '' },
  { label: '黑色', value: '#111827' },
  { label: '红色', value: '#b91c1c' },
  { label: '蓝色', value: '#1d4ed8' },
  { label: '绿色', value: '#047857' },
  { label: '灰色', value: '#4b5563' },
];

const HIGHLIGHT_COLORS: SelectOption[] = [
  { label: '无高亮', value: '' },
  { label: '黄色', value: '#fef08a' },
  { label: '绿色', value: '#bbf7d0' },
  { label: '蓝色', value: '#bfdbfe' },
  { label: '粉色', value: '#fecdd3' },
  { label: '紫色', value: '#ddd6fe' },
];

const TABLE_ACTIONS: SelectOption[] = [
  { label: '表格操作', value: '' },
  { label: '插入 3x3 表格', value: 'insert' },
  { label: '在后面插入行', value: 'row-after' },
  { label: '在后面插入列', value: 'column-after' },
  { label: '删除当前行', value: 'delete-row' },
  { label: '删除当前列', value: 'delete-column' },
  { label: '删除表格', value: 'delete-table' },
];

const selectClass = 'h-8 rounded-md border border-outline-variant/60 bg-surface-lowest px-2 text-xs text-foreground/75 outline-none transition-colors hover:border-primary/35 focus:border-primary/60';

function deferEditorCommand(callback: () => void): () => void {
  let cancelled = false;
  const run = () => {
    if (!cancelled) callback();
  };
  if (typeof queueMicrotask === 'function') {
    queueMicrotask(run);
  } else {
    globalThis.setTimeout(run, 0);
  }
  return () => {
    cancelled = true;
  };
}

function getMarkdown(editor: Editor): string {
  return (editor.storage as unknown as { markdown: MarkdownStorage }).markdown.getMarkdown();
}

interface ClipboardImageReference {
  src: string;
  alt: string;
  caption?: string;
}

function extractMarkdownImageReference(text: string): ClipboardImageReference | null {
  const trimmed = text.trim();
  const match = trimmed.match(/^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/);
  if (!match?.[2]) return null;
  const caption = trimmed.slice(match[0].length).replace(/^\s+/, '').trim();
  return {
    alt: match[1]?.trim() ?? '',
    src: match[2].trim(),
    caption: caption || undefined,
  };
}

function insertImageNode(view: EditorView, image: ClipboardImageReference): boolean {
  const imageType = view.state.schema.nodes.image;
  const paragraphType = view.state.schema.nodes.paragraph;
  if (!imageType || !image.src.trim()) return false;
  const nodes = [
    imageType.create({ src: image.src.trim(), alt: image.alt.trim() || null }),
  ];
  const caption = image.caption?.replace(/\s+/g, ' ').trim();
  if (caption && paragraphType) {
    nodes.push(paragraphType.create(null, view.state.schema.text(caption)));
  }
  view.dispatch(view.state.tr.replaceSelection(new Slice(Fragment.fromArray(nodes), 0, 0)).scrollIntoView());
  return true;
}

function firstPastedImageFile(clipboardData: DataTransfer): File | null {
  const fileFromFiles = Array.from(clipboardData.files).find((file) => file.type.startsWith('image/'));
  if (fileFromFiles) return fileFromFiles;
  const fileItem = Array.from(clipboardData.items).find((item) => item.kind === 'file' && item.type.startsWith('image/'));
  return fileItem?.getAsFile() ?? null;
}

function MenuBar({ editor }: { editor: Editor | null }) {
  if (!editor) return null;
  const textStyle = editor.getAttributes('textStyle') as {
    color?: string;
    fontFamily?: string;
    fontSize?: string;
    lineHeight?: string;
  };
  const highlight = editor.getAttributes('highlight') as { color?: string };
  const currentBlock = editor.isActive('heading', { level: 1 })
    ? 'h1'
    : editor.isActive('heading', { level: 2 })
      ? 'h2'
      : editor.isActive('heading', { level: 3 })
        ? 'h3'
        : 'paragraph';

  const buttonClass = (active: boolean, disabled = false) =>
    cn(
      'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors',
      active ? 'bg-primary/15 text-primary' : 'text-foreground/50 hover:bg-surface-container hover:text-foreground/80',
      disabled && 'cursor-not-allowed opacity-40 hover:bg-transparent',
    );
  const setFontFamily = (value: string) => {
    if (value) editor.chain().focus().setFontFamily(value).run();
    else editor.chain().focus().unsetFontFamily().run();
  };
  const setFontSize = (value: string) => {
    if (value) editor.chain().focus().setFontSize(value).run();
    else editor.chain().focus().unsetFontSize().run();
  };
  const setTextColor = (value: string) => {
    if (value) editor.chain().focus().setColor(value).run();
    else editor.chain().focus().unsetColor().run();
  };
  const setLineHeight = (value: string) => {
    if (value) editor.chain().focus().setLineHeight(value).run();
    else editor.chain().focus().unsetLineHeight().run();
  };
  const setHighlight = (value: string) => {
    if (value) editor.chain().focus().setHighlight({ color: value }).run();
    else editor.chain().focus().unsetHighlight().run();
  };
  const handleBlockChange = (value: string) => {
    if (value === 'paragraph') editor.chain().focus().setParagraph().run();
    if (value === 'h1') editor.chain().focus().toggleHeading({ level: 1 }).run();
    if (value === 'h2') editor.chain().focus().toggleHeading({ level: 2 }).run();
    if (value === 'h3') editor.chain().focus().toggleHeading({ level: 3 }).run();
  };
  const handleTableAction = (value: string) => {
    if (value === 'insert') editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
    if (value === 'row-after') editor.chain().focus().addRowAfter().run();
    if (value === 'column-after') editor.chain().focus().addColumnAfter().run();
    if (value === 'delete-row') editor.chain().focus().deleteRow().run();
    if (value === 'delete-column') editor.chain().focus().deleteColumn().run();
    if (value === 'delete-table') editor.chain().focus().deleteTable().run();
  };
  const insertImage = () => {
    const url = window.prompt('请输入图片地址：');
    if (url?.trim()) {
      editor.chain().focus().setImage({ src: url.trim() }).run();
    }
  };
  const clearFormatting = () => {
    editor.chain().focus().unsetAllMarks().clearNodes().unsetTextAlign().unsetHighlight().run();
  };

  return (
    <div className="sticky top-0 z-10 -mx-10 -mt-8 mb-6 flex flex-wrap items-center gap-1 border-b border-outline-variant bg-surface-low px-4 py-2">
      <select value={currentBlock} onChange={(event) => handleBlockChange(event.target.value)} aria-label="段落样式" title="段落样式" className={cn(selectClass, 'w-[104px]')}>
        <option value="paragraph">正文</option>
        <option value="h1">标题 1</option>
        <option value="h2">标题 2</option>
        <option value="h3">标题 3</option>
      </select>
      <select value={textStyle.fontFamily ?? ''} onChange={(event) => setFontFamily(event.target.value)} aria-label="字体" title="字体" className={cn(selectClass, 'w-[132px]')}>
        {FONT_FAMILIES.map((font) => <option key={font.label} value={font.value}>{font.label}</option>)}
      </select>
      <select value={textStyle.fontSize ?? ''} onChange={(event) => setFontSize(event.target.value)} aria-label="字号" title="字号" className={cn(selectClass, 'w-[72px]')}>
        <option value="">字号</option>
        {FONT_SIZES.map((size) => <option key={size.value} value={size.value}>{size.label}</option>)}
      </select>
      <select value={textStyle.lineHeight ?? ''} onChange={(event) => setLineHeight(event.target.value)} aria-label="行距" title="行距" className={cn(selectClass, 'w-[82px]')}>
        <option value="">行距</option>
        {LINE_HEIGHTS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>
      <span className="mx-1 h-6 w-px shrink-0 bg-outline-variant/50" aria-hidden />
      <button type="button" onClick={() => editor.chain().focus().toggleBold().run()} className={buttonClass(editor.isActive('bold'))} aria-label="加粗" title="加粗"><Bold size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleItalic().run()} className={buttonClass(editor.isActive('italic'))} aria-label="斜体" title="斜体"><Italic size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleUnderline().run()} className={buttonClass(editor.isActive('underline'))} aria-label="下划线" title="下划线"><UnderlineIcon size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleStrike().run()} className={buttonClass(editor.isActive('strike'))} aria-label="删除线" title="删除线"><Strikethrough size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleSuperscript().run()} className={buttonClass(editor.isActive('superscript'))} aria-label="上标" title="上标"><SuperscriptIcon size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleSubscript().run()} className={buttonClass(editor.isActive('subscript'))} aria-label="下标" title="下标"><SubscriptIcon size={15} /></button>
      <select value={textStyle.color ?? ''} onChange={(event) => setTextColor(event.target.value)} aria-label="字体颜色" title="字体颜色" className={cn(selectClass, 'w-[88px]')}>
        {TEXT_COLORS.map((color) => <option key={color.label} value={color.value}>{color.label}</option>)}
      </select>
      <select value={highlight.color ?? ''} onChange={(event) => setHighlight(event.target.value)} aria-label="文本高亮" title="文本高亮" className={cn(selectClass, 'w-[92px]')}>
        {HIGHLIGHT_COLORS.map((color) => <option key={color.label} value={color.value}>{color.label}</option>)}
      </select>
      <span className="mx-1 h-6 w-px shrink-0 bg-outline-variant/50" aria-hidden />
      <button type="button" onClick={() => editor.chain().focus().toggleBulletList().run()} className={buttonClass(editor.isActive('bulletList'))} aria-label="项目符号列表" title="项目符号列表"><List size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleOrderedList().run()} className={buttonClass(editor.isActive('orderedList'))} aria-label="编号列表" title="编号列表"><ListOrdered size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleBlockquote().run()} className={buttonClass(editor.isActive('blockquote'))} aria-label="引用块" title="引用块"><Quote size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().toggleCodeBlock().run()} className={buttonClass(editor.isActive('codeBlock'))} aria-label="代码块" title="代码块"><Code2 size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().setHorizontalRule().run()} className={buttonClass(false)} aria-label="分割线" title="分割线"><Minus size={15} /></button>
      <span className="mx-1 h-6 w-px shrink-0 bg-outline-variant/50" aria-hidden />
      <button type="button" onClick={() => editor.chain().focus().setTextAlign('left').run()} className={buttonClass(editor.isActive({ textAlign: 'left' }))} aria-label="左对齐" title="左对齐"><AlignLeft size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().setTextAlign('center').run()} className={buttonClass(editor.isActive({ textAlign: 'center' }))} aria-label="居中对齐" title="居中对齐"><AlignCenter size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().setTextAlign('right').run()} className={buttonClass(editor.isActive({ textAlign: 'right' }))} aria-label="右对齐" title="右对齐"><AlignRight size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().setTextAlign('justify').run()} className={buttonClass(editor.isActive({ textAlign: 'justify' }))} aria-label="两端对齐" title="两端对齐"><AlignJustify size={15} /></button>
      <span className="mx-1 h-6 w-px shrink-0 bg-outline-variant/50" aria-hidden />
      <select
        value=""
        onChange={(event) => {
          handleTableAction(event.target.value);
          event.currentTarget.value = '';
        }}
        aria-label="表格操作"
        title="表格操作"
        className={cn(selectClass, 'w-[110px]')}
      >
        {TABLE_ACTIONS.map((action) => <option key={action.value || action.label} value={action.value}>{action.label}</option>)}
      </select>
      <button type="button" onClick={insertImage} className={buttonClass(false)} aria-label="插入图片" title="插入图片"><ImagePlus size={15} /></button>
      <span className="mx-1 h-6 w-px shrink-0 bg-outline-variant/50" aria-hidden />
      <button type="button" onClick={() => editor.chain().focus().undo().run()} disabled={!editor.can().undo()} className={buttonClass(false, !editor.can().undo())} aria-label="撤销" title="撤销"><Undo size={15} /></button>
      <button type="button" onClick={() => editor.chain().focus().redo().run()} disabled={!editor.can().redo()} className={buttonClass(false, !editor.can().redo())} aria-label="重做" title="重做"><Redo size={15} /></button>
      <button type="button" onClick={clearFormatting} className={buttonClass(false)} aria-label="清除格式" title="清除格式"><Eraser size={15} /></button>
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
      StarterKit.configure({ heading: { levels: [1, 2, 3] }, underline: false }),
      Underline,
      Superscript,
      Subscript,
      TextStyleKit,
      Highlight.configure({ multicolor: true }),
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      Image.configure({ inline: false, allowBase64: true }),
      Table.configure({ resizable: true }),
      TableRow,
      TableCell,
      TableHeader,
      Placeholder.configure({ placeholder: placeholder || '' }),
      Markdown.configure({ html: true, transformPastedText: true, transformCopiedText: true }),
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
      handlePaste: (view, event) => {
        const clipboardData = event.clipboardData;
        if (!clipboardData) return false;

        const markdownImage = extractMarkdownImageReference(clipboardData.getData('text/plain'));
        const pastedImage = firstPastedImageFile(clipboardData);
        if (pastedImage) {
          const reader = new FileReader();
          reader.onload = () => {
            if (typeof reader.result !== 'string') return;
            insertImageNode(view, {
              src: reader.result,
              alt: markdownImage?.alt || pastedImage.name,
              caption: markdownImage?.caption || markdownImage?.alt,
            });
          };
          reader.readAsDataURL(pastedImage);
          return true;
        }

        return markdownImage ? insertImageNode(view, markdownImage) : false;
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
    return deferEditorCommand(() => {
      if (editor.isDestroyed) return;
      const current = getMarkdown(editor);
      if (content === current) return;
      applyingExternalRef.current = true;
      try {
        editor.commands.setContent(content);
      } finally {
        applyingExternalRef.current = false;
      }
      lastSerializedRef.current = content;
    });
  }, [content, editor]);

  // Citation insertion requested from the toolbar / reference drawer.
  useEffect(() => {
    const request = citationInsertRequest;
    if (!editor || !request || handledInsertRef.current === request.requestId) return;

    handledInsertRef.current = request.requestId;
    return deferEditorCommand(() => {
      if (editor.isDestroyed) return;
      const anchorId = createCitationAnchorId(request.materialId);
      editor.chain().focus().insertCitation(anchorId).run();

      const nextContent = getMarkdown(editor);
      const tokenOffset = nextContent.indexOf(`[^${anchorId}]`);
      const instanceId = getCitationAnchorInstanceId(anchorId, tokenOffset >= 0 ? tokenOffset : 0);
      onCitationInsertHandled(request.requestId, instanceId, request.materialId);
    });
  }, [citationInsertRequest, editor, onCitationInsertHandled]);

  // Locate request: select + scroll to the matching citation node.
  useEffect(() => {
    const request = citationFocusRequest;
    if (!editor || !request || handledFocusRef.current === request.requestId) return;

    handledFocusRef.current = request.requestId;
    return deferEditorCommand(() => {
      if (editor.isDestroyed) return;
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
    });
  }, [citationFocusRequest, editor, onCitationFocusHandled]);

  return (
    <div className={className}>
      <MenuBar editor={editor} />
      <EditorContent editor={editor} />
    </div>
  );
}
