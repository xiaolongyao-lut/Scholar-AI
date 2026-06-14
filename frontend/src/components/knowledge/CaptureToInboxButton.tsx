import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { FilePlus2, Loader2, Square, X } from 'lucide-react';

import { cn } from '@/lib/utils';
import { createWikiManualPage, WikiApiError } from '@/services/wikiApi';
import type { WikiManualPageInputModel, WikiManualPageKind, WikiManualPageStatus } from '@/types/wiki';

export type CaptureContextKind = 'pdf' | 'dialog' | 'writing' | 'generic';

export interface CaptureContext {
  /**
   * 上下文类型：决定默认标题前缀和上下文段落格式。
   */
  kind: CaptureContextKind;
  /** 来源对象（论文标题 / 对话 / 章节）的可读名 */
  sourceLabel?: string;
  /** 引用片段（高亮文本 / 答复正文 / 选区） */
  quote?: string;
  /** 业务 id：material_id / session_id / project_id 等，仅写入 body 注脚做溯源 */
  rawIds?: Record<string, string | number | null | undefined>;
  /** 页码、消息序号等位置信息 */
  locator?: string;
}

interface CaptureToInboxButtonProps {
  context: CaptureContext;
  /** 触发按钮样式：full=带文字，icon=仅图标 */
  variant?: 'full' | 'icon';
  /** 触发按钮的额外类名 */
  className?: string;
  /** 自定义按钮标签，默认是「记一下」 */
  label?: string;
}

const KIND_DEFAULTS: Record<CaptureContextKind, { defaultKind: WikiManualPageKind; titlePrefix: string }> = {
  pdf: { defaultKind: 'exploration', titlePrefix: '论文笔记' },
  dialog: { defaultKind: 'synthesis', titlePrefix: '对话洞察' },
  writing: { defaultKind: 'concept', titlePrefix: '写作片段' },
  generic: { defaultKind: 'concept', titlePrefix: '想法' },
};

function buildInitialTitle(context: CaptureContext): string {
  const prefix = KIND_DEFAULTS[context.kind].titlePrefix;
  if (context.sourceLabel) {
    return `${prefix}：${context.sourceLabel}`.slice(0, 80);
  }
  return prefix;
}

function buildContextFooter(context: CaptureContext): string {
  const lines: string[] = [];
  if (context.sourceLabel) lines.push(`来源：${context.sourceLabel}`);
  if (context.locator) lines.push(`位置：${context.locator}`);
  const rawEntries = Object.entries(context.rawIds ?? {}).filter(([, value]) => value !== undefined && value !== null && value !== '');
  if (rawEntries.length > 0) {
    lines.push(`原始标识：${rawEntries.map(([k, v]) => `${k}=${v}`).join(', ')}`);
  }
  return lines.length === 0 ? '' : `\n\n---\n${lines.join('\n')}\n`;
}

function buildInitialBody(context: CaptureContext): string {
  const quote = context.quote?.trim();
  const footer = buildContextFooter(context);
  if (quote) {
    return `> ${quote.split('\n').join('\n> ')}\n\n（在这里写你的想法）${footer}`;
  }
  return `（在这里写你的想法）${footer}`;
}

/**
 * 可复用的「记一下」入口：在阅读 / 对话 / 写作中弹出一个轻量表单。
 * 当前后端会创建待确认 Wiki 草稿，并同步进入 ReviewQueue。
 *
 * 输入：调用方提供的来源/引用/上下文 id。
 * 输出：UI 按钮 + 弹出表单 + 写入提示。所有 raw id 仅落到 body 注脚和 extra，
 *       不暴露在主流程标签上。
 */
export function CaptureToInboxButton({ context, variant = 'full', className, label = '记一下' }: CaptureToInboxButtonProps) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(buildInitialTitle(context));
  const [body, setBody] = useState(buildInitialBody(context));
  const [kind, setKind] = useState<WikiManualPageKind>(KIND_DEFAULTS[context.kind].defaultKind);
  const status: WikiManualPageStatus = 'review';
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const titleInputId = useId();
  const bodyInputId = useId();

  // 当上下文（如新选区）变化时，重置默认填充值；如果用户已经改过表单则保留改动。
  useEffect(() => {
    if (!open) {
      setTitle(buildInitialTitle(context));
      setBody(buildInitialBody(context));
      setKind(KIND_DEFAULTS[context.kind].defaultKind);
    }
  }, [context, open]);

  const handleOpen = () => {
    setError(null);
    setSuccessMessage(null);
    setOpen(true);
  };

  const handleClose = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = null;
    setOpen(false);
    setIsSubmitting(false);
  }, []);

  const handleSubmit = useCallback(async () => {
    const trimmedTitle = title.trim();
    const trimmedBody = body.trim();
    if (!trimmedTitle || !trimmedBody) {
      setError('标题和内容不能为空。');
      return;
    }
    const abortController = new AbortController();
    abortRef.current = abortController;
    setIsSubmitting(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const input: WikiManualPageInputModel = {
        title: trimmedTitle,
        kind,
        status,
        body: trimmedBody,
      };
      const result = await createWikiManualPage(input, 15000, { signal: abortController.signal });
      if (abortController.signal.aborted) return;
      setSuccessMessage(`已保存为待确认草稿。（${result.slug || '已记录'}）`);
      // 成功后清空 quote 让下一次记录从空表单开始
      setBody(buildInitialBody({ ...context, quote: '' }));
    } catch (err: unknown) {
      if (abortController.signal.aborted) return;
      if (err instanceof WikiApiError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message === 'Failed to fetch' ? '后端不可达，请确认服务已启动。' : err.message);
      } else {
        setError('保存失败，请稍后重试。');
      }
    } finally {
      if (abortRef.current === abortController) {
        abortRef.current = null;
        setIsSubmitting(false);
      }
    }
  }, [body, context, kind, status, title]);

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/15',
          variant === 'icon' && 'px-1.5 py-1',
          className,
        )}
        aria-label={label}
      >
        <FilePlus2 size={13} />
        {variant === 'full' ? <span>{label}</span> : null}
      </button>

      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="记一下 — 保存为待确认草稿"
          className="fixed inset-0 z-50 flex items-end justify-center bg-foreground/40 px-4 py-6 sm:items-center"
          onClick={handleClose}
        >
          <div
            className="w-full max-w-xl overflow-hidden rounded-lg border border-outline-variant/60 bg-surface-low shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="flex items-center justify-between border-b border-outline-variant/60 bg-surface-lowest px-4 py-3">
              <div className="flex items-center gap-2 text-foreground">
                <FilePlus2 size={15} className="text-primary" />
                <h2 className="font-headline text-sm font-semibold">记一下</h2>
                <span className="text-[11px] text-foreground/45">待确认</span>
              </div>
              <button
                type="button"
                onClick={handleClose}
                className="rounded-md border border-outline-variant/50 p-1 text-foreground/55 transition-colors hover:border-primary/30 hover:text-foreground"
                aria-label="关闭"
              >
                <X size={13} />
              </button>
            </header>

            <div className="space-y-3 px-4 py-4">
              <label className="block text-xs text-foreground/55" htmlFor={titleInputId}>
                <span className="font-label text-[11px] text-foreground/45">标题</span>
                <input
                  id={titleInputId}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                />
              </label>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block text-xs text-foreground/55">
                  <span className="font-label text-[11px] text-foreground/45">类型</span>
                  <select
                    value={kind}
                    onChange={(event) => setKind(event.target.value as WikiManualPageKind)}
                    className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm text-foreground focus:border-primary/40 focus:outline-none"
                  >
                    <option value="concept">概念</option>
                    <option value="synthesis">综合结论</option>
                    <option value="exploration">探索记录</option>
                    <option value="experiment">实验结果</option>
                    <option value="question">问题</option>
                    <option value="paper">论文摘要</option>
                  </select>
                </label>
                <div className="rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2">
                  <div className="font-label text-[11px] text-foreground/45">保存位置</div>
                  <div className="mt-1 text-sm text-foreground">待确认草稿</div>
                </div>
              </div>

              <label className="block text-xs text-foreground/55" htmlFor={bodyInputId}>
                <span className="font-label text-[11px] text-foreground/45">内容</span>
                <textarea
                  id={bodyInputId}
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                  rows={8}
                  className="mt-1.5 w-full rounded-md border border-outline-variant/50 bg-surface-high px-3 py-2 text-sm leading-6 text-foreground placeholder:text-foreground/30 focus:border-primary/40 focus:outline-none"
                />
              </label>

              {error ? (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
                  {error}
                </div>
              ) : null}

              {successMessage ? (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300">
                  {successMessage}
                </div>
              ) : null}
            </div>

            <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-outline-variant/60 bg-surface-lowest px-4 py-3">
              <span className="text-[11px] text-foreground/45">复审后沉淀</span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleClose}
                  className="rounded-md border border-outline-variant/50 px-3 py-1.5 text-xs text-foreground/65 transition-colors hover:border-primary/30 hover:text-foreground"
                >
                  关闭
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (isSubmitting) {
                      abortRef.current?.abort();
                      abortRef.current = null;
                      setIsSubmitting(false);
                      setError('已停止保存。');
                      return;
                    }
                    void handleSubmit();
                  }}
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSubmitting ? <Loader2 size={13} className="animate-spin" /> : <Square size={0} aria-hidden className="hidden" />}
                  {isSubmitting ? '停止' : '保存待确认草稿'}
                </button>
              </div>
            </footer>
          </div>
        </div>
      ) : null}
    </>
  );
}

export default CaptureToInboxButton;
