import type { ForwardRefExoticComponent, RefAttributes, SVGProps } from 'react';
import { FileCode2, FileText, FileType } from 'lucide-react';

import {
  WRITING_DOCUMENT_EXPORT_FORMATS,
  type WritingDocumentExportFormat,
  type WritingExportFormat,
} from '@/services/writingBackend';

type ExportIcon = ForwardRefExoticComponent<
  RefAttributes<SVGSVGElement>
  & Partial<SVGProps<SVGSVGElement>>
  & { size?: string | number; absoluteStrokeWidth?: boolean }
>;

interface DocumentExportOptionMeta {
  label: string;
  extension: string;
  description: string;
  Icon: ExportIcon;
}

export interface DocumentExportOption extends DocumentExportOptionMeta {
  format: WritingDocumentExportFormat;
}

const DOCUMENT_EXPORT_OPTION_META = {
  latex: {
    label: 'LaTeX',
    extension: '.tex',
    description: '排版源文件',
    Icon: FileCode2,
  },
  markdown: {
    label: 'Markdown',
    extension: '.md',
    description: '轻量文稿',
    Icon: FileText,
  },
  word: {
    label: 'Word',
    extension: '.docx',
    description: '成稿文档',
    Icon: FileType,
  },
} satisfies Record<WritingDocumentExportFormat, DocumentExportOptionMeta>;

export const DOCUMENT_EXPORT_OPTIONS: readonly DocumentExportOption[] = WRITING_DOCUMENT_EXPORT_FORMATS.map((format) => ({
  format,
  ...DOCUMENT_EXPORT_OPTION_META[format],
}));

export function isWritingDocumentExportFormat(format: WritingExportFormat): format is WritingDocumentExportFormat {
  return WRITING_DOCUMENT_EXPORT_FORMATS.includes(format as WritingDocumentExportFormat);
}

export function getDocumentExportOption(format: WritingDocumentExportFormat): DocumentExportOption {
  return {
    format,
    ...DOCUMENT_EXPORT_OPTION_META[format],
  };
}

export function writingExportFormatLabel(format: WritingExportFormat): string {
  if (isWritingDocumentExportFormat(format)) {
    return DOCUMENT_EXPORT_OPTION_META[format].label;
  }
  const fallbackLabels: Record<Exclude<WritingExportFormat, WritingDocumentExportFormat>, string> = {
    json: '结构化文件',
    pdf: 'PDF 文件',
  };
  return fallbackLabels[format];
}
