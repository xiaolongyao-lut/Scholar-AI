import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Underline } from '@tiptap/extension-underline';
import { TextAlign } from '@tiptap/extension-text-align';
import { Placeholder } from '@tiptap/extension-placeholder';
import { Heading } from '@tiptap/extension-heading';
import { Image } from '@tiptap/extension-image';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { TextStyleKit } from '@tiptap/extension-text-style';
import { Highlight } from '@tiptap/extension-highlight';
import { Superscript } from '@tiptap/extension-superscript';
import { Subscript } from '@tiptap/extension-subscript';
import type { ReactNode } from 'react';
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

interface TipTapEditorProps {
  content: string;
  onChange: (html: string, json: object) => void;
  placeholder?: string;
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

function ToolbarButton({
  active = false,
  disabled = false,
  label,
  onClick,
  children,
}: {
  active?: boolean;
  disabled?: boolean;
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors',
        active
          ? 'bg-primary/15 text-primary'
          : 'text-foreground/50 hover:bg-surface-container hover:text-foreground/80',
        disabled && 'cursor-not-allowed opacity-40 hover:bg-transparent',
      )}
      aria-label={label}
      title={label}
    >
      {children}
    </button>
  );
}

function Divider() {
  return <span className="mx-1 h-6 w-px shrink-0 bg-outline-variant/50" aria-hidden />;
}

function MenuBar({ editor }: { editor: ReturnType<typeof useEditor> }) {
  if (!editor) return null;

  const textStyle = editor.getAttributes('textStyle') as {
    color?: string;
    fontFamily?: string;
    fontSize?: string;
    lineHeight?: string;
  };
  const highlight = editor.getAttributes('highlight') as { color?: string };

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
  const handleImageInsert = () => {
    const url = window.prompt('请输入图片地址：');
    if (!url?.trim()) return;

    const trimmedUrl = url.trim();

    // Security: validate image URL scheme
    try {
      const parsed = new URL(trimmedUrl);
      const allowedSchemes = ['https:', 'http:', 'blob:', 'data:'];

      if (!allowedSchemes.includes(parsed.protocol)) {
        window.alert(
          `不支持的图片协议：${parsed.protocol}\n` +
          `仅允许：https、http、blob、data`
        );
        return;
      }

      // Additional validation for data: URLs
      if (parsed.protocol === 'data:') {
        const MAX_DATA_URL_SIZE = 5 * 1024 * 1024; // 5 MB
        if (trimmedUrl.length > MAX_DATA_URL_SIZE) {
          window.alert(
            `data: URL 过大 (${(trimmedUrl.length / 1024 / 1024).toFixed(1)} MB)\n` +
            `最大限制：5 MB`
          );
          return;
        }

        // Validate data: URL format (data:image/...;base64,...)
        if (!trimmedUrl.startsWith('data:image/')) {
          window.alert('data: URL 必须是图片类型（data:image/...）');
          return;
        }
      }

      editor.chain().focus().setImage({ src: trimmedUrl }).run();
    } catch (err) {
      // Not a valid URL, allow relative paths
      if (!trimmedUrl.includes('://')) {
        editor.chain().focus().setImage({ src: trimmedUrl }).run();
      } else {
        window.alert(`无效的图片地址：${err instanceof Error ? err.message : String(err)}`);
      }
    }
  };
  const clearFormatting = () => {
    editor.chain().focus().unsetAllMarks().clearNodes().unsetTextAlign().unsetHighlight().run();
  };
  const currentBlock = editor.isActive('heading', { level: 1 })
    ? 'h1'
    : editor.isActive('heading', { level: 2 })
      ? 'h2'
      : editor.isActive('heading', { level: 3 })
        ? 'h3'
        : 'paragraph';

  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-outline-variant bg-surface-low px-3 py-2">
      <select
        value={currentBlock}
        onChange={(event) => handleBlockChange(event.target.value)}
        aria-label="段落样式"
        title="段落样式"
        className={cn(selectClass, 'w-[104px]')}
      >
        <option value="paragraph">正文</option>
        <option value="h1">标题 1</option>
        <option value="h2">标题 2</option>
        <option value="h3">标题 3</option>
      </select>
      <select
        value={textStyle.fontFamily ?? ''}
        onChange={(event) => setFontFamily(event.target.value)}
        aria-label="字体"
        title="字体"
        className={cn(selectClass, 'w-[132px]')}
      >
        {FONT_FAMILIES.map((font) => (
          <option key={font.label} value={font.value}>{font.label}</option>
        ))}
      </select>
      <select
        value={textStyle.fontSize ?? ''}
        onChange={(event) => setFontSize(event.target.value)}
        aria-label="字号"
        title="字号"
        className={cn(selectClass, 'w-[72px]')}
      >
        <option value="">字号</option>
        {FONT_SIZES.map((size) => (
          <option key={size.value} value={size.value}>{size.label}</option>
        ))}
      </select>
      <select
        value={textStyle.lineHeight ?? ''}
        onChange={(event) => setLineHeight(event.target.value)}
        aria-label="行距"
        title="行距"
        className={cn(selectClass, 'w-[82px]')}
      >
        <option value="">行距</option>
        {LINE_HEIGHTS.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>

      <Divider />
      <ToolbarButton label="加粗" active={editor.isActive('bold')} onClick={() => editor.chain().focus().toggleBold().run()}>
        <Bold size={15} />
      </ToolbarButton>
      <ToolbarButton label="斜体" active={editor.isActive('italic')} onClick={() => editor.chain().focus().toggleItalic().run()}>
        <Italic size={15} />
      </ToolbarButton>
      <ToolbarButton label="下划线" active={editor.isActive('underline')} onClick={() => editor.chain().focus().toggleUnderline().run()}>
        <UnderlineIcon size={15} />
      </ToolbarButton>
      <ToolbarButton label="删除线" active={editor.isActive('strike')} onClick={() => editor.chain().focus().toggleStrike().run()}>
        <Strikethrough size={15} />
      </ToolbarButton>
      <ToolbarButton label="上标" active={editor.isActive('superscript')} onClick={() => editor.chain().focus().toggleSuperscript().run()}>
        <SuperscriptIcon size={15} />
      </ToolbarButton>
      <ToolbarButton label="下标" active={editor.isActive('subscript')} onClick={() => editor.chain().focus().toggleSubscript().run()}>
        <SubscriptIcon size={15} />
      </ToolbarButton>
      <select
        value={textStyle.color ?? ''}
        onChange={(event) => setTextColor(event.target.value)}
        aria-label="字体颜色"
        title="字体颜色"
        className={cn(selectClass, 'w-[88px]')}
      >
        {TEXT_COLORS.map((color) => (
          <option key={color.label} value={color.value}>{color.label}</option>
        ))}
      </select>
      <select
        value={highlight.color ?? ''}
        onChange={(event) => setHighlight(event.target.value)}
        aria-label="文本高亮"
        title="文本高亮"
        className={cn(selectClass, 'w-[92px]')}
      >
        {HIGHLIGHT_COLORS.map((color) => (
          <option key={color.label} value={color.value}>{color.label}</option>
        ))}
      </select>

      <Divider />
      <ToolbarButton label="项目符号列表" active={editor.isActive('bulletList')} onClick={() => editor.chain().focus().toggleBulletList().run()}>
        <List size={15} />
      </ToolbarButton>
      <ToolbarButton label="编号列表" active={editor.isActive('orderedList')} onClick={() => editor.chain().focus().toggleOrderedList().run()}>
        <ListOrdered size={15} />
      </ToolbarButton>
      <ToolbarButton label="引用块" active={editor.isActive('blockquote')} onClick={() => editor.chain().focus().toggleBlockquote().run()}>
        <Quote size={15} />
      </ToolbarButton>
      <ToolbarButton label="代码块" active={editor.isActive('codeBlock')} onClick={() => editor.chain().focus().toggleCodeBlock().run()}>
        <Code2 size={15} />
      </ToolbarButton>
      <ToolbarButton label="分割线" onClick={() => editor.chain().focus().setHorizontalRule().run()}>
        <Minus size={15} />
      </ToolbarButton>

      <Divider />
      <ToolbarButton label="左对齐" active={editor.isActive({ textAlign: 'left' })} onClick={() => editor.chain().focus().setTextAlign('left').run()}>
        <AlignLeft size={15} />
      </ToolbarButton>
      <ToolbarButton label="居中对齐" active={editor.isActive({ textAlign: 'center' })} onClick={() => editor.chain().focus().setTextAlign('center').run()}>
        <AlignCenter size={15} />
      </ToolbarButton>
      <ToolbarButton label="右对齐" active={editor.isActive({ textAlign: 'right' })} onClick={() => editor.chain().focus().setTextAlign('right').run()}>
        <AlignRight size={15} />
      </ToolbarButton>
      <ToolbarButton label="两端对齐" active={editor.isActive({ textAlign: 'justify' })} onClick={() => editor.chain().focus().setTextAlign('justify').run()}>
        <AlignJustify size={15} />
      </ToolbarButton>

      <Divider />
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
        {TABLE_ACTIONS.map((action) => (
          <option key={action.value || action.label} value={action.value}>{action.label}</option>
        ))}
      </select>
      <ToolbarButton label="插入图片" onClick={handleImageInsert}>
        <ImagePlus size={15} />
      </ToolbarButton>

      <Divider />
      <ToolbarButton label="撤销" disabled={!editor.can().undo()} onClick={() => editor.chain().focus().undo().run()}>
        <Undo size={15} />
      </ToolbarButton>
      <ToolbarButton label="重做" disabled={!editor.can().redo()} onClick={() => editor.chain().focus().redo().run()}>
        <Redo size={15} />
      </ToolbarButton>
      <ToolbarButton label="清除格式" onClick={clearFormatting}>
        <Eraser size={15} />
      </ToolbarButton>
    </div>
  );
}

/**
 * Word-like rich text editor used by Manuscript Studio.
 *
 * It emits both HTML and TipTap JSON so the surrounding writing runtime can
 * keep its existing save contract while the toolbar stores typography as
 * inline marks.
 */
export function TipTapEditor({ content, onChange, placeholder, className }: TipTapEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: false }),
      Heading.configure({ levels: [1, 2, 3] }),
      Underline,
      Superscript,
      Subscript,
      TextStyleKit,
      Highlight.configure({ multicolor: true }),
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      Placeholder.configure({ placeholder: placeholder || '开始写作…' }),
      Image.configure({
        inline: false,
        allowBase64: true, // Allow but validate in handleImageInsert
      }),
      Table.configure({ resizable: true }),
      TableRow,
      TableCell,
      TableHeader,
    ],
    content,
    onUpdate: ({ editor: currentEditor }) => {
      onChange(currentEditor.getHTML(), currentEditor.getJSON());
    },
    editorProps: {
      attributes: {
        class: 'prose prose-sm sm:prose-base max-w-none focus:outline-none min-h-[60vh] text-gray-800 dark:text-foreground',
      },
    },
  });

  return (
    <div className={cn('rounded-sm border border-outline-variant/60 bg-white shadow-[0_2px_12px_0_rgba(0,0,0,0.06)] dark:bg-surface-lowest dark:shadow-[0_2px_12px_0_rgba(0,0,0,0.25)]', className)}>
      <MenuBar editor={editor} />
      <div className="px-10 py-8">
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}
