import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type CompositionEvent,
  type Dispatch,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type SetStateAction,
} from 'react';
import {
  Image as ImageIcon,
  Loader2,
  Paperclip,
  ScanSearch,
  Send,
  Sigma,
  Square,
  Table2,
  TextQuote,
  X,
} from 'lucide-react';
import { ProjectBiasSurfaceToggle } from '@/components/knowledge/ProjectBiasSurfaceToggle';
import { cn } from '@/lib/utils';

/**
 * Image attachment payload (Dialog Vision P0).
 *
 * Limits are hard-coded per the fullstack-dedup plan (Dialog requirement):
 *   - max 6 images
 *   - 4 MB per image
 *   - PNG / JPEG / WebP / GIF
 *   - sent with the chat request for optional SmartRead vision assistance
 *
 * Shape matches the legacy `ImageAttachment` from intelligentChatApi so
 * Dialog's submit payload forwards the same `images` field consumed by the
 * backend vision-auxiliary path.
 */
export interface ChatAttachment {
  /** MIME type, e.g. `image/png`. */
  mime: string;
  /** Base64-encoded body (no data URL prefix). */
  data_b64: string;
  /** Original file size in bytes. */
  size: number;
  /** Original file name; optional but used in alt text + remove tooltip. */
  name?: string;
}

export type ChatSelectionKind = 'text' | 'figure' | 'table' | 'formula' | 'region';

export interface ChatSelectionContext {
  /** Optional only for the legacy singular selection prop. */
  id?: string;
  kind: ChatSelectionKind;
  page: number;
  label: string;
  text?: string | null;
  /** Identifies the hidden pixel payload paired with a visual PDF selection. */
  attachmentFingerprint?: string;
}

export type IdentifiedChatSelectionContext = ChatSelectionContext & { id: string };

export interface ChatInputSubmitPayload {
  text: string;
  attachments: ChatAttachment[];
  attachmentsEnabled: boolean;
  projectReasoningBiasEnabled?: boolean;
}

export interface ChatInputHandle {
  /** Programmatic focus, used after asynchronous actions such as selecting a starter suggestion. */
  focus(options?: { selection?: 'start' | 'end' | 'all' }): void;
  /** Focuses the composer and selects the full draft text. */
  selectAll(): void;
  /** Clears the draft text without touching image attachments. */
  clear(): void;
  /** Adds validated image attachments produced by another in-app surface. */
  appendAttachments(attachments: ChatAttachment[]): boolean;
  /** Replaces only the hidden pixels paired with the current PDF selection. */
  replaceSelectionAttachment(
    previousAttachmentFingerprint: string | null | undefined,
    nextAttachment?: ChatAttachment,
  ): boolean;
}

interface ChatInputProps {
  /** Called when the user submits (Enter / Cmd+Enter depending on
   *  `submitKey`). Receives the current text + attachments + a boolean
   *  that mirrors the `enableAttachments` prop so callers can decide
   *  whether to forward the attachment array to the backend. */
  onSubmit(payload: ChatInputSubmitPayload): void;
  /** Optional controlled draft value for pages that persist composer text. */
  value?: string;
  /** Optional controlled draft change callback. */
  onValueChange?: (value: string) => void;
  /** Placeholder copy. Defaults to a Chinese-friendly generic prompt. */
  placeholder?: string;
  /** Disable the composer while a response is streaming. */
  disabled?: boolean;
  /** True while a model request is active; shows an interrupt control. */
  responding?: boolean;
  /** Cancel the active model request. */
  onStop?: () => void;
  /** Visible label for stop semantics. Defaults to the generic composer copy. */
  stopLabel?: string;
  /** Which key combination submits the message.
   *  - `enter` — Enter sends, Shift+Enter newline (Dialog legacy)
   *  - `cmd-enter` — Ctrl/Cmd+Enter sends, Enter newline (Inspector legacy) */
  submitKey?: 'enter' | 'cmd-enter';
  /** Number of textarea rows; defaults to 2. */
  rows?: number;
  /** Image attachments capability. When false (default), the paperclip
   *  button and thumbnail tray are not rendered. Inspector omits this;
   *  Dialog opts in with `enableAttachments`. */
  enableAttachments?: boolean;
  /** Optional controlled attachment draft for layouts that remount the composer. */
  attachments?: ChatAttachment[];
  /** Controlled attachment draft change callback. */
  onAttachmentsChange?: Dispatch<SetStateAction<ChatAttachment[]>>;
  /** Parent-owned pending FileReader count, preserved when the composer remounts. */
  pendingAttachmentReads?: number;
  /** Functional setter paired with `pendingAttachmentReads`. */
  onPendingAttachmentReadsChange?: Dispatch<SetStateAction<number>>;
  /** Typed PDF selection shown without exposing its paired screenshot. */
  selectionContext?: ChatSelectionContext | null;
  /** Clears the parent-owned PDF selection after removing its paired pixels. */
  onClearSelectionContext?: () => void;
  /** Canonical ordered PDF selections shown without exposing paired screenshots. */
  selectionContexts?: readonly IdentifiedChatSelectionContext[];
  /** Removes exactly one canonical PDF selection by its stable id. */
  onRemoveSelectionContext?: (id: string) => void;
  /** Footer hint shown below the input (e.g. shortcut reminder). */
  hint?: string;
  /** Stable accessible name for automation and assistive tech. */
  ariaLabel?: string;
  /** Focus the textarea when this composer first mounts. */
  autoFocus?: boolean;
  /** Extra classes for the outer wrapper. */
  className?: string;
  /** Optional current-request project reasoning-bias toggle. */
  projectReasoningBias?: {
    enabled: boolean;
    available: boolean;
    loading?: boolean;
    onChange: (enabled: boolean) => void;
  };
}

const VISION_MAX_IMAGES = 6;
const VISION_MAX_BYTES = 4 * 1024 * 1024; // 4 MB
const VISION_ALLOWED_MIME = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
const VISION_ACCEPT = Array.from(VISION_ALLOWED_MIME).join(',');
const ATTACHMENT_ONLY_PROMPT = '请分析这些图片。';
const LEGACY_SELECTION_CONTEXT_ID = 'legacy-pdf-selection';
const SELECTION_KIND_LABELS: Record<ChatSelectionKind, string> = {
  text: '选中的文本',
  figure: '选中的图',
  table: '选中的表',
  formula: '选中的公式',
  region: '选中的区域',
};
const SELECTION_KIND_ICONS = {
  text: TextQuote,
  figure: ImageIcon,
  table: Table2,
  formula: Sigma,
  region: ScanSearch,
} satisfies Record<ChatSelectionKind, typeof TextQuote>;

interface AttachmentMergeResult {
  attachments: ChatAttachment[];
  addedCount: number;
  warning: string | null;
}

function mergeAttachments(
  current: ChatAttachment[],
  incoming: ChatAttachment[],
): AttachmentMergeResult {
  const next = [...current];
  const seen = new Set(current.map((item) => `${item.mime}:${item.data_b64}`));
  let addedCount = 0;
  let warning: string | null = null;
  for (const attachment of incoming) {
    if (!VISION_ALLOWED_MIME.has(attachment.mime)) {
      warning = '仅支持 PNG、JPEG、WebP 或 GIF 图片。';
      continue;
    }
    if (!Number.isFinite(attachment.size) || attachment.size <= 0 || attachment.size > VISION_MAX_BYTES) {
      warning = `单张图片不能超过 ${VISION_MAX_BYTES / 1024 / 1024} MB。`;
      continue;
    }
    if (!attachment.data_b64.trim()) {
      warning = '图片内容为空，未添加。';
      continue;
    }
    const key = `${attachment.mime}:${attachment.data_b64}`;
    if (seen.has(key)) continue;
    if (next.length >= VISION_MAX_IMAGES) {
      warning = `单次最多添加 ${VISION_MAX_IMAGES} 张图片。`;
      break;
    }
    seen.add(key);
    next.push(attachment);
    addedCount += 1;
  }
  return { attachments: next, addedCount, warning };
}

export function chatAttachmentFingerprint(attachment: ChatAttachment): string {
  let hash = 2166136261;
  for (let index = 0; index < attachment.data_b64.length; index += 1) {
    hash ^= attachment.data_b64.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `${attachment.mime}:${attachment.size}:${hash >>> 0}`;
}

function selectionTextPreview(value: string | null | undefined): string | null {
  const normalized = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!normalized) return null;
  return normalized.length > 160 ? `${normalized.slice(0, 157)}...` : normalized;
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== 'string') {
        reject(new Error('FileReader returned non-string result'));
        return;
      }
      const commaIdx = result.indexOf(',');
      resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error('FileReader error'));
    reader.readAsDataURL(file);
  });
}

/**
 * Canonical chat composer.
 *
 * Single textarea + send button shared by Inspector smart-read and Dialog.
 * Attachments are opt-in via `enableAttachments`; the tray sits above the
 * textarea, the paperclip lives on the bottom-left, send on the right —
 * matches Slack / Stream Chat composer conventions. Submit payload includes
 * `attachments` + `attachmentsEnabled` so Dialog and Inspector can share the
 * same backend image-handling contract.
 */
export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  {
    onSubmit,
    value,
    onValueChange,
    placeholder = '输入你的问题…',
    disabled = false,
    responding = false,
    onStop,
    stopLabel = '停止生成',
    submitKey = 'cmd-enter',
    rows = 2,
    enableAttachments = false,
    attachments: controlledAttachments,
    onAttachmentsChange,
    pendingAttachmentReads,
    onPendingAttachmentReadsChange,
    hint,
    ariaLabel = '对话输入',
    autoFocus = false,
    className,
    projectReasoningBias,
    selectionContext,
    onClearSelectionContext,
    selectionContexts,
    onRemoveSelectionContext,
  },
  ref,
) {
  const [uncontrolledText, setUncontrolledText] = useState('');
  const [uncontrolledAttachments, setUncontrolledAttachments] = useState<ChatAttachment[]>([]);
  const attachments = controlledAttachments ?? uncontrolledAttachments;
  const attachmentsRef = useRef<ChatAttachment[]>(attachments);
  const [uncontrolledReadingCount, setUncontrolledReadingCount] = useState(0);
  const controlledReadingCount = pendingAttachmentReads === undefined
    ? undefined
    : Number.isFinite(pendingAttachmentReads)
      ? Math.max(0, Math.trunc(pendingAttachmentReads))
      : 0;
  const readingCount = controlledReadingCount ?? uncontrolledReadingCount;
  const readingCountRef = useRef(readingCount);
  const [limitWarning, setLimitWarning] = useState<string | null>(null);
  const composingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaId = useId();
  const text = value ?? uncontrolledText;
  const setText = useCallback((next: string) => {
    if (value === undefined) {
      setUncontrolledText(next);
    }
    onValueChange?.(next);
  }, [onValueChange, value]);

  useEffect(() => {
    attachmentsRef.current = attachments;
  }, [attachments]);

  useEffect(() => {
    readingCountRef.current = readingCount;
  }, [readingCount]);

  const commitAttachments = useCallback((action: SetStateAction<ChatAttachment[]>): void => {
    if (typeof action !== 'function') {
      attachmentsRef.current = action;
      if (controlledAttachments === undefined) {
        setUncontrolledAttachments(action);
      }
      onAttachmentsChange?.(action);
      return;
    }

    if (controlledAttachments === undefined) {
      const next = action(attachmentsRef.current);
      attachmentsRef.current = next;
      setUncontrolledAttachments(next);
      onAttachmentsChange?.(next);
      return;
    }

    if (!onAttachmentsChange) {
      attachmentsRef.current = action(attachmentsRef.current);
      return;
    }
    onAttachmentsChange((current) => {
      const next = action(current);
      attachmentsRef.current = next;
      return next;
    });
  }, [controlledAttachments, onAttachmentsChange]);

  const updateReadingCount = useCallback((action: SetStateAction<number>): void => {
    const resolve = (current: number): number => {
      const next = typeof action === 'function' ? action(current) : action;
      return Number.isFinite(next) ? Math.max(0, Math.trunc(next)) : 0;
    };
    readingCountRef.current = resolve(readingCountRef.current);
    if (pendingAttachmentReads === undefined) {
      setUncontrolledReadingCount(readingCountRef.current);
    }
    onPendingAttachmentReadsChange?.((current) => resolve(current));
  }, [onPendingAttachmentReadsChange, pendingAttachmentReads]);

  const focusComposer = useCallback((selection: 'start' | 'end' | 'all' = 'end') => {
    if (disabled) return;
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.focus({ preventScroll: true });
    const length = textarea.value.length;
    if (selection === 'all') {
      textarea.setSelectionRange(0, length);
    } else if (selection === 'start') {
      textarea.setSelectionRange(0, 0);
    } else {
      textarea.setSelectionRange(length, length);
    }
  }, [disabled]);

  const appendAttachments = useCallback((incoming: ChatAttachment[]): boolean => {
    if (!enableAttachments || incoming.length === 0) return false;
    if (disabled) {
      setLimitWarning('回答生成中，暂不能添加图片。');
      return false;
    }
    const preview = mergeAttachments(attachmentsRef.current, incoming);
    commitAttachments(preview.attachments);
    setLimitWarning(preview.warning);
    return preview.addedCount > 0;
  }, [commitAttachments, disabled, enableAttachments]);

  const replaceSelectionAttachment = useCallback((
    previousAttachmentFingerprint: string | null | undefined,
    nextAttachment?: ChatAttachment,
  ): boolean => {
    if (!enableAttachments) return false;
    if (disabled) {
      setLimitWarning('回答生成中，暂不能更换 PDF 选区。');
      return false;
    }

    const normalizedPreviousFingerprint = previousAttachmentFingerprint?.trim() ?? '';
    const retained = normalizedPreviousFingerprint
      ? attachmentsRef.current.filter(
          (attachment) => chatAttachmentFingerprint(attachment) !== normalizedPreviousFingerprint,
        )
      : attachmentsRef.current;
    const replacement = nextAttachment
      ? mergeAttachments(retained, [nextAttachment])
      : { attachments: retained, addedCount: 0, warning: null };

    if (nextAttachment && replacement.addedCount === 0) {
      setLimitWarning(replacement.warning ?? '所选内容与现有图片附件重复，未更新 PDF 选区。');
      return false;
    }

    commitAttachments(replacement.attachments);
    setLimitWarning(replacement.warning);
    return true;
  }, [commitAttachments, disabled, enableAttachments]);

  useImperativeHandle(ref, () => ({
    focus(options) {
      focusComposer(options?.selection ?? 'end');
    },
    selectAll() {
      focusComposer('all');
    },
    clear() {
      if (disabled) return;
      setText('');
      window.setTimeout(() => focusComposer('start'), 0);
    },
    appendAttachments,
    replaceSelectionAttachment,
  }), [
    appendAttachments,
    disabled,
    focusComposer,
    replaceSelectionAttachment,
    setText,
  ]);

  useEffect(() => {
    if (!autoFocus || disabled) return undefined;
    const timer = window.setTimeout(() => focusComposer('end'), 0);
    return () => window.clearTimeout(timer);
  }, [autoFocus, disabled, focusComposer]);

  const send = useCallback(() => {
    if (disabled || readingCountRef.current > 0) return;
    const trimmed = text.trim();
    if (!trimmed && attachments.length === 0) return;
    onSubmit({
      text: trimmed || ATTACHMENT_ONLY_PROMPT,
      attachments: enableAttachments ? attachments : [],
      attachmentsEnabled: enableAttachments,
      projectReasoningBiasEnabled: projectReasoningBias?.available ? projectReasoningBias.enabled : undefined,
    });
    setText('');
    commitAttachments([]);
    setLimitWarning(null);
  }, [text, attachments, disabled, onSubmit, enableAttachments, setText, projectReasoningBias, commitAttachments]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // IME composition guard: while the user is typing a CJK candidate,
      // Enter commits the candidate and must not submit the message.
      if (composingRef.current) return;
      if (e.key !== 'Enter') return;
      const withModifier = e.metaKey || e.ctrlKey;
      const shouldSubmit =
        submitKey === 'enter' ? !e.shiftKey : withModifier;
      if (shouldSubmit) {
        e.preventDefault();
        send();
      }
    },
    [submitKey, send],
  );

  const handleComposition = useCallback((e: CompositionEvent<HTMLTextAreaElement>) => {
    composingRef.current = e.type !== 'compositionend';
  }, []);

  const handleFilePick = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      if (!enableAttachments) return;
      const files = Array.from(e.target.files ?? []);
      e.target.value = '';
      if (files.length === 0) return;
      const remaining = VISION_MAX_IMAGES
        - attachmentsRef.current.length
        - readingCountRef.current;
      if (remaining <= 0) {
        setLimitWarning(`最多 ${VISION_MAX_IMAGES} 张图片`);
        return;
      }
      const slice = files.slice(0, remaining);
      if (files.length > remaining) {
        setLimitWarning(`只能再添加 ${remaining} 张图片，已忽略多余文件`);
      } else {
        setLimitWarning(null);
      }
      updateReadingCount((current) => current + slice.length);
      const accepted: ChatAttachment[] = [];
      try {
        for (const file of slice) {
          if (!VISION_ALLOWED_MIME.has(file.type)) {
            setLimitWarning(`不支持的图片类型：${file.type || '未知'}`);
            continue;
          }
          if (file.size > VISION_MAX_BYTES) {
            setLimitWarning(`「${file.name}」超过 ${VISION_MAX_BYTES / 1024 / 1024} MB 单图上限`);
            continue;
          }
          try {
            const data_b64 = await fileToBase64(file);
            accepted.push({ mime: file.type, data_b64, size: file.size, name: file.name });
          } catch {
            setLimitWarning(`无法读取「${file.name}」`);
          }
        }
        const preview = mergeAttachments(attachmentsRef.current, accepted);
        commitAttachments((current) => mergeAttachments(current, accepted).attachments);
        if (preview.warning) {
          setLimitWarning(preview.warning);
        }
      } finally {
        updateReadingCount((current) => current - slice.length);
      }
    },
    [enableAttachments, commitAttachments, updateReadingCount],
  );

  const removeAttachment = useCallback((idx: number) => {
    commitAttachments(attachmentsRef.current.filter((_, i) => i !== idx));
  }, [commitAttachments]);

  const usesCanonicalSelectionContexts = selectionContexts !== undefined;
  const activeSelectionContexts: readonly IdentifiedChatSelectionContext[] = usesCanonicalSelectionContexts
    ? selectionContexts
    : selectionContext
      ? [{
          ...selectionContext,
          id: selectionContext.id?.trim() || LEGACY_SELECTION_CONTEXT_ID,
        }]
      : [];

  const handleRemoveSelectionContext = useCallback((context: IdentifiedChatSelectionContext) => {
    if (disabled) return;
    const fingerprint = context.attachmentFingerprint?.trim();
    if (fingerprint) {
      commitAttachments(attachmentsRef.current.filter(
        (attachment) => chatAttachmentFingerprint(attachment) !== fingerprint,
      ));
    }
    setLimitWarning(null);
    onRemoveSelectionContext?.(context.id);
    if (!usesCanonicalSelectionContexts) {
      onClearSelectionContext?.();
    }
  }, [
    commitAttachments,
    disabled,
    onClearSelectionContext,
    onRemoveSelectionContext,
    usesCanonicalSelectionContexts,
  ]);

  const hiddenSelectionFingerprints = new Set(
    activeSelectionContexts
      .map((context) => context.attachmentFingerprint?.trim())
      .filter((fingerprint): fingerprint is string => Boolean(fingerprint)),
  );
  const visibleAttachmentEntries = attachments
    .map((attachment, index) => ({ attachment, index }))
    .filter(({ attachment }) => !hiddenSelectionFingerprints.has(chatAttachmentFingerprint(attachment)));
  const hiddenSelectionAttachmentCount = attachments.reduce(
    (count, attachment) => (
      hiddenSelectionFingerprints.has(chatAttachmentFingerprint(attachment)) ? count + 1 : count
    ),
    0,
  );
  const visibleAttachmentLimit = VISION_MAX_IMAGES - hiddenSelectionAttachmentCount;
  const canAttachMore =
    enableAttachments && attachments.length + readingCount < VISION_MAX_IMAGES;
  const submitDisabled = disabled
    || readingCount > 0
    || (!text.trim() && attachments.length === 0);
  const hasDraftText = text.length > 0;
  const handleClearDraft = useCallback(() => {
    if (disabled || !hasDraftText) return;
    setText('');
    window.setTimeout(() => focusComposer('start'), 0);
  }, [disabled, focusComposer, hasDraftText, setText]);
  const handleClearDraftPressStart = useCallback((
    event: MouseEvent<HTMLButtonElement> | PointerEvent<HTMLButtonElement>,
  ) => {
    if (disabled || !hasDraftText) return;
    event.preventDefault();
    handleClearDraft();
  }, [disabled, handleClearDraft, hasDraftText]);

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {activeSelectionContexts.length > 0 && (
        <div
          role="group"
          aria-label="当前 PDF 选区"
          className="max-h-36 divide-y divide-outline-variant/40 overflow-y-auto rounded-md border border-primary/30 bg-primary/5"
        >
          {activeSelectionContexts.map((context, index) => {
            const selectionLabel = SELECTION_KIND_LABELS[context.kind];
            const selectionPage = Number.isInteger(context.page) && context.page > 0
              ? context.page
              : null;
            const selectionPreview = context.kind === 'text'
              ? selectionTextPreview(context.text)
              : null;
            const SelectionIcon = SELECTION_KIND_ICONS[context.kind];
            const removeLabel = activeSelectionContexts.length === 1
              ? `移除${selectionLabel}`
              : `移除选区 ${index + 1}：${selectionLabel}${selectionPage === null ? '' : `，第 ${selectionPage} 页`}`;

            return (
              <div key={context.id} className="flex min-w-0 items-center gap-2 px-2.5 py-1.5">
                <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded bg-surface-lowest text-primary">
                  <SelectionIcon className="h-3.5 w-3.5" aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-1.5 text-xs">
                    <span className="truncate font-medium text-foreground/80">{selectionLabel}</span>
                    {selectionPage !== null && (
                      <span className="shrink-0 text-foreground/45">第 {selectionPage} 页</span>
                    )}
                  </div>
                  {selectionPreview && (
                    <p className="truncate text-[11px] text-foreground/55" title={selectionPreview}>
                      {selectionPreview}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => handleRemoveSelectionContext(context)}
                  disabled={disabled}
                  aria-label={removeLabel}
                  title="移除选区"
                  className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-foreground/45 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {enableAttachments && (visibleAttachmentEntries.length > 0 || readingCount > 0) && (
        <div className="flex flex-wrap items-center gap-2">
          {visibleAttachmentEntries.map(({ attachment: img, index }) => (
            <div key={`${img.name ?? 'img'}-${index}`} className="group relative">
              <img
                src={`data:${img.mime};base64,${img.data_b64}`}
                alt={img.name ?? `附件图片 ${index + 1}`}
                className="h-14 w-14 rounded-md border border-outline-variant/60 object-cover"
              />
              <button
                type="button"
                onClick={() => removeAttachment(index)}
                aria-label={`移除「${img.name ?? `图片 ${index + 1}`}」`}
                title="移除图片"
                className="absolute -right-1.5 -top-1.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-foreground/80 text-background opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
          {readingCount > 0 && (
            <div
              role="status"
              aria-label="正在读取图片"
              className="flex h-14 w-14 items-center justify-center rounded-md border border-dashed border-outline-variant/60 bg-surface-lowest"
            >
              <Loader2 className="h-4 w-4 animate-spin text-foreground/40" />
            </div>
          )}
          <span className="font-label text-[10px] text-foreground/45">
            图片附件 {visibleAttachmentEntries.length}/{visibleAttachmentLimit}
          </span>
        </div>
      )}

      {enableAttachments && limitWarning && (
        <p className="font-label text-[11px] text-amber-700 dark:text-amber-300">⚠ {limitWarning}</p>
      )}

      {projectReasoningBias && (
        <div className="flex flex-wrap items-center gap-2">
          <ProjectBiasSurfaceToggle
            enabled={projectReasoningBias.enabled && projectReasoningBias.available}
            label={projectReasoningBias.enabled && projectReasoningBias.available ? '项目偏置已启用' : '项目偏置已关闭'}
            disabled={!projectReasoningBias.available || projectReasoningBias.loading || disabled}
            onChange={projectReasoningBias.onChange}
          />
          <span className="text-[10px] text-foreground/40">
            {projectReasoningBias.available ? '仅影响本次发送' : '当前项目未启用聊天偏置'}
          </span>
        </div>
      )}

      <div className="flex items-end gap-2">
        <label htmlFor={textareaId} className="sr-only">
          {ariaLabel}
        </label>
        {enableAttachments && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept={VISION_ACCEPT}
              multiple
              onChange={handleFilePick}
              className="hidden"
              aria-label="选择图片附件"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={disabled || !canAttachMore}
              aria-label={`添加图片附件，最多 ${VISION_MAX_IMAGES} 张，单张 ≤ ${VISION_MAX_BYTES / 1024 / 1024} MB`}
              title={`添加图片附件（最多 ${VISION_MAX_IMAGES} 张，单张 ≤ ${VISION_MAX_BYTES / 1024 / 1024} MB）`}
              className="shrink-0 inline-flex items-center justify-center rounded-md border border-outline-variant/60 bg-surface-lowest px-2.5 py-2 text-foreground/70 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Paperclip className="h-4 w-4" />
            </button>
          </>
        )}

        <textarea
          id={textareaId}
          ref={textareaRef}
          name="scholar-ai-question"
          data-scholar-ai-role="smartread-composer-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={handleComposition}
          onCompositionEnd={handleComposition}
          onCompositionUpdate={handleComposition}
          disabled={disabled}
          rows={rows}
          placeholder={placeholder}
          aria-multiline="true"
          autoFocus={autoFocus}
          className="min-h-[44px] max-h-48 flex-1 resize-y rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-2 text-sm text-foreground placeholder:text-foreground/35 focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:cursor-not-allowed disabled:bg-surface-low"
        />

        <button
          type="button"
          onPointerDown={handleClearDraftPressStart}
          onPointerUp={handleClearDraftPressStart}
          onMouseDown={handleClearDraftPressStart}
          onMouseUp={handleClearDraftPressStart}
          onClick={handleClearDraft}
          disabled={disabled || !hasDraftText}
          aria-label="清空输入"
          title="清空输入"
          tabIndex={hasDraftText ? 0 : -1}
          style={{ visibility: hasDraftText ? 'visible' : 'hidden' }}
          className="shrink-0 inline-flex h-9 w-9 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-lowest text-foreground/60 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>

        {responding && onStop ? (
          <button
            type="button"
            onClick={onStop}
            aria-label={stopLabel}
            title={stopLabel}
            className="shrink-0 inline-flex items-center justify-center rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700 transition-colors hover:bg-red-100 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
            <span className="sr-only">{stopLabel}</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={send}
            disabled={submitDisabled}
            aria-label="发送"
            className="shrink-0 inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Send className="h-3.5 w-3.5" />
            发送
          </button>
        )}
      </div>

      {hint && <p className="font-label text-[10px] text-foreground/40">{hint}</p>}
    </div>
  );
});

export const CHAT_INPUT_VISION_LIMITS = {
  maxImages: VISION_MAX_IMAGES,
  maxBytes: VISION_MAX_BYTES,
  allowedMime: VISION_ALLOWED_MIME,
} as const;
