import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useState,
  type ChangeEvent,
  type CompositionEvent,
  type KeyboardEvent,
} from 'react';
import { Loader2, Paperclip, Send, Square, X } from 'lucide-react';
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

export interface ChatInputSubmitPayload {
  text: string;
  attachments: ChatAttachment[];
  attachmentsEnabled: boolean;
  projectReasoningBiasEnabled?: boolean;
}

export interface ChatInputHandle {
  /** Programmatic focus, used by callers that want to refocus the composer
   *  after asynchronous actions (e.g. selecting a starter suggestion). */
  focus(): void;
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
  /** Footer hint shown below the input (e.g. shortcut reminder). */
  hint?: string;
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
    submitKey = 'cmd-enter',
    rows = 2,
    enableAttachments = false,
    hint,
    className,
    projectReasoningBias,
  },
  ref,
) {
  const [uncontrolledText, setUncontrolledText] = useState('');
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [readingCount, setReadingCount] = useState(0);
  const [limitWarning, setLimitWarning] = useState<string | null>(null);
  const composingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const text = value ?? uncontrolledText;
  const setText = useCallback((next: string) => {
    if (value === undefined) {
      setUncontrolledText(next);
    }
    onValueChange?.(next);
  }, [onValueChange, value]);

  useImperativeHandle(ref, () => ({
    focus() {
      textareaRef.current?.focus();
    },
  }));

  const send = useCallback(() => {
    if (disabled) return;
    const trimmed = text.trim();
    if (!trimmed && attachments.length === 0) return;
    onSubmit({
      text: trimmed,
      attachments: enableAttachments ? attachments : [],
      attachmentsEnabled: enableAttachments,
      projectReasoningBiasEnabled: projectReasoningBias?.available ? projectReasoningBias.enabled : undefined,
    });
    setText('');
    setAttachments([]);
    setLimitWarning(null);
  }, [text, attachments, disabled, onSubmit, enableAttachments, setText, projectReasoningBias]);

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
      const remaining = VISION_MAX_IMAGES - attachments.length - readingCount;
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
      setReadingCount((c) => c + slice.length);
      const accepted: ChatAttachment[] = [];
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
      setAttachments((prev) => [...prev, ...accepted]);
      setReadingCount((c) => Math.max(0, c - slice.length));
    },
    [enableAttachments, attachments.length, readingCount],
  );

  const removeAttachment = useCallback((idx: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const canAttachMore =
    enableAttachments && attachments.length + readingCount < VISION_MAX_IMAGES;
  const submitDisabled = disabled || (!text.trim() && attachments.length === 0);

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {enableAttachments && (attachments.length > 0 || readingCount > 0) && (
        <div className="flex flex-wrap items-center gap-2">
          {attachments.map((img, idx) => (
            <div key={`${img.name ?? 'img'}-${idx}`} className="group relative">
              <img
                src={`data:${img.mime};base64,${img.data_b64}`}
                alt={img.name ?? `附件图片 ${idx + 1}`}
                className="h-14 w-14 rounded-md border border-outline-variant/60 object-cover"
              />
              <button
                type="button"
                onClick={() => removeAttachment(idx)}
                aria-label={`移除「${img.name ?? `图片 ${idx + 1}`}」`}
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
            {attachments.length}/{VISION_MAX_IMAGES} · 图片会随本次提问发送；配置视觉辅助后会自动生成图片上下文
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
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={handleComposition}
          onCompositionEnd={handleComposition}
          onCompositionUpdate={handleComposition}
          disabled={disabled}
          rows={rows}
          placeholder={placeholder}
          className="min-h-[44px] max-h-48 flex-1 resize-y rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-2 text-sm text-foreground placeholder:text-foreground/35 focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:cursor-not-allowed disabled:bg-surface-low"
        />

        {responding && onStop ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="停止生成"
            title="停止生成"
            className="shrink-0 inline-flex items-center justify-center rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700 transition-colors hover:bg-red-100 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
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
