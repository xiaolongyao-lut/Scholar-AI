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
import {
  Bold, Italic, Underline as UnderlineIcon, Strikethrough,
  Heading1, Heading2, Heading3, List, ListOrdered,
  AlignLeft, AlignCenter, AlignRight, AlignJustify,
  Undo, Redo, ImagePlus, Table as TableIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface TipTapEditorProps {
  content: string;
  onChange: (html: string, json: object) => void;
  placeholder?: string;
  className?: string;
}

const MenuBar = ({ editor }: { editor: ReturnType<typeof useEditor> }) => {
  if (!editor) return null;

  const btnClass = (isActive: boolean) =>
    cn(
      'p-1.5 rounded transition-colors',
      isActive
        ? 'bg-primary/15 text-primary'
        : 'text-foreground/40 hover:bg-surface-container hover:text-foreground/70'
    );

  return (
    <div className="flex flex-wrap items-center gap-0.5 px-3 py-2 border-b border-outline-variant bg-surface-low">
      <button onClick={() => editor.chain().focus().toggleBold().run()} className={btnClass(editor.isActive('bold'))} title="Bold"><Bold size={15} /></button>
      <button onClick={() => editor.chain().focus().toggleItalic().run()} className={btnClass(editor.isActive('italic'))} title="Italic"><Italic size={15} /></button>
      <button onClick={() => editor.chain().focus().toggleUnderline().run()} className={btnClass(editor.isActive('underline'))} title="Underline"><UnderlineIcon size={15} /></button>
      <button onClick={() => editor.chain().focus().toggleStrike().run()} className={btnClass(editor.isActive('strike'))} title="Strikethrough"><Strikethrough size={15} /></button>
      <span className="w-px h-5 bg-outline-variant/50 mx-1" />
      <button onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} className={btnClass(editor.isActive('heading', { level: 1 }))} title="H1"><Heading1 size={15} /></button>
      <button onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} className={btnClass(editor.isActive('heading', { level: 2 }))} title="H2"><Heading2 size={15} /></button>
      <button onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} className={btnClass(editor.isActive('heading', { level: 3 }))} title="H3"><Heading3 size={15} /></button>
      <span className="w-px h-5 bg-outline-variant/50 mx-1" />
      <button onClick={() => editor.chain().focus().toggleBulletList().run()} className={btnClass(editor.isActive('bulletList'))} title="Bullet List"><List size={15} /></button>
      <button onClick={() => editor.chain().focus().toggleOrderedList().run()} className={btnClass(editor.isActive('orderedList'))} title="Ordered List"><ListOrdered size={15} /></button>
      <span className="w-px h-5 bg-outline-variant/50 mx-1" />
      <button onClick={() => editor.chain().focus().setTextAlign('left').run()} className={btnClass(editor.isActive({ textAlign: 'left' }))} title="Align Left"><AlignLeft size={15} /></button>
      <button onClick={() => editor.chain().focus().setTextAlign('center').run()} className={btnClass(editor.isActive({ textAlign: 'center' }))} title="Align Center"><AlignCenter size={15} /></button>
      <button onClick={() => editor.chain().focus().setTextAlign('right').run()} className={btnClass(editor.isActive({ textAlign: 'right' }))} title="Align Right"><AlignRight size={15} /></button>
      <button onClick={() => editor.chain().focus().setTextAlign('justify').run()} className={btnClass(editor.isActive({ textAlign: 'justify' }))} title="Justify"><AlignJustify size={15} /></button>
      <span className="w-px h-5 bg-outline-variant/50 mx-1" />
      <button onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()} className={btnClass(false)} title="Insert Table"><TableIcon size={15} /></button>
      <button
        onClick={() => {
          const url = window.prompt('Image URL:');
          if (url) editor.chain().focus().setImage({ src: url }).run();
        }}
        className={btnClass(false)} title="Insert Image"
      ><ImagePlus size={15} /></button>
      <span className="w-px h-5 bg-outline-variant/50 mx-1" />
      <button onClick={() => editor.chain().focus().undo().run()} className={btnClass(false)} title="Undo"><Undo size={15} /></button>
      <button onClick={() => editor.chain().focus().redo().run()} className={btnClass(false)} title="Redo"><Redo size={15} /></button>
    </div>
  );
};

export function TipTapEditor({ content, onChange, placeholder, className }: TipTapEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: false }),
      Heading.configure({ levels: [1, 2, 3] }),
      Underline,
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      Placeholder.configure({ placeholder: placeholder || 'Start writing...' }),
      Image,
      Table.configure({ resizable: true }),
      TableRow,
      TableCell,
      TableHeader,
    ],
    content,
    onUpdate: ({ editor: e }) => {
      onChange(e.getHTML(), e.getJSON());
    },
    editorProps: {
      attributes: {
        class: 'prose prose-sm sm:prose-base max-w-none focus:outline-none min-h-[60vh] text-gray-800 dark:text-foreground',
      },
    },
  });

  return (
    <div className={cn('rounded-sm border border-outline-variant/60 bg-white dark:bg-surface-lowest shadow-[0_2px_12px_0_rgba(0,0,0,0.06)] dark:shadow-[0_2px_12px_0_rgba(0,0,0,0.25)]', className)}>
      <MenuBar editor={editor} />
      <div className="px-10 py-8">
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}
