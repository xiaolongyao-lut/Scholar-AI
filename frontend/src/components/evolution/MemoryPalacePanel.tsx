import { BookOpenCheck, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { cn } from '@/lib/utils';
import {
  listMemoryPalaceMemories,
  type MemoryListPayload,
  type MemoryRecordPayload,
} from '../../services/memoryPalaceApi';
import {
  formatEvolutionError,
  sanitizeEvolutionDetailText,
  sanitizeEvolutionUserText,
} from './labels';

const DEFAULT_MEMORY_LIMIT = 6;

function metadataText(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function metadataNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function lineValue(text: string, key: string): string | null {
  const pattern = new RegExp(`^${key}:\\s*(.+)$`, 'im');
  const match = text.match(pattern);
  return match?.[1]?.trim() || null;
}

function jobKindLabel(kind: string | null): string {
  const labels: Record<string, string> = {
    prompt_action: '提示处理',
    skill_action: '流程执行',
    figure_load: '图表读取',
    export: '导出',
    compile: '编译',
  };
  return kind ? labels[kind] ?? '运行任务' : '运行任务';
}

function jobStatusLabel(status: string | null): string {
  const labels: Record<string, string> = {
    completed: '已完成',
    failed: '失败',
    running: '运行中',
    pending: '等待中',
    cancelled: '已取消',
  };
  return status ? labels[status] ?? '已记录' : '已记录';
}

function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    'writing-runtime': '写作运行时',
    'local-memory': '本地长期记忆',
  };
  return labels[source] ?? source;
}

function roomLabel(room: string): string {
  const labels: Record<string, string> = {
    'runtime-jobs-prompt-action': '提示处理任务',
    'runtime-jobs-skill-action': '流程执行任务',
  };
  return labels[room] ?? sanitizeEvolutionUserText(room.replace(/[-_]+/g, ' '), '通用记忆');
}

function wingLabel(wing: string): string {
  const labels: Record<string, string> = {
    wing_modular_pipeline: '研究工作流',
  };
  return labels[wing] ?? sanitizeEvolutionUserText(wing.replace(/^wing[_-]?/, '').replace(/[-_]+/g, ' '), '研究范围');
}

function extractError(text: string): string | null {
  const raw = lineValue(text, 'error');
  if (!raw) {
    return null;
  }
  if (/^[\x00-\x7F]+$/.test(raw)) {
    return '任务失败，原始错误已隐藏。';
  }
  return sanitizeEvolutionDetailText(raw, '任务失败，原始错误已隐藏。', 120);
}

function extractArtifactNames(text: string): string[] {
  const section = text.split(/^##\s+Artifacts\s*$/im)[1]?.split(/^##\s+/m)[0] ?? '';
  const names = Array.from(section.matchAll(/^\[([^\]\n]+)\]/gm))
    .map((match) => sanitizeEvolutionUserText(match[1], '任务产物'))
    .filter((value, index, list) => list.indexOf(value) === index);
  return names.slice(0, 3);
}

function buildMemorySummary(memory: MemoryRecordPayload): {
  title: string;
  summary: string;
  detail: string;
  status: string;
  kind: string;
} {
  const kind = metadataText(memory.metadata, 'job_kind') ?? lineValue(memory.text, 'kind');
  const status = metadataText(memory.metadata, 'job_status') ?? lineValue(memory.text, 'status');
  const artifactCount = metadataNumber(memory.metadata, 'artifact_count');
  const eventCount = metadataNumber(memory.metadata, 'event_count');
  const error = extractError(memory.text);
  const artifactNames = extractArtifactNames(memory.text);
  const isRuntimeMemory = /^##\s+Runtime Job Memory/im.test(memory.text) || kind !== null || status !== null;

  if (isRuntimeMemory) {
    const title = `${jobKindLabel(kind)}经验`;
    const countParts = [
      artifactCount !== null ? `${artifactCount} 个产物` : null,
      eventCount !== null ? `${eventCount} 条运行事件` : null,
    ].filter((part): part is string => part !== null);
    const summary = `记录了一次${jobKindLabel(kind)}任务，状态为${jobStatusLabel(status)}${countParts.length ? `，包含${countParts.join('、')}` : ''}。`;
    const detail = error
      ? `失败原因：${error}`
      : artifactNames.length
        ? `可复用线索：${artifactNames.join('、')}。`
        : '可用于判断同类任务是否需要保存为流程经验。';
    return { title, summary, detail, status: jobStatusLabel(status), kind: jobKindLabel(kind) };
  }

  return {
    title: '长期记忆条目',
    summary: sanitizeEvolutionDetailText(memory.text, '这条长期记忆包含内部诊断信息，已在界面隐藏。', 180),
    detail: '已保存到本地长期记忆，可作为后续任务参考。',
    status: '已记录',
    kind: '通用记忆',
  };
}

function MemorySkeleton() {
  return (
    <div className="grid gap-2 md:grid-cols-2">
      {Array.from({ length: 2 }, (_, index) => (
        <div
          key={index}
          className="h-28 animate-pulse rounded-md border border-outline-variant/40 bg-surface-low"
        />
      ))}
    </div>
  );
}

function MemoryCard({ memory }: { memory: MemoryRecordPayload }) {
  const summary = buildMemorySummary(memory);
  const wing = wingLabel(memory.wing);
  const room = roomLabel(memory.room);
  const source = sourceLabel(sanitizeEvolutionUserText(memory.source_file, '本地长期记忆'));

  return (
    <article className="min-h-28 rounded-md border border-outline-variant/45 bg-surface-low px-3 py-3">
      <div className="flex min-w-0 items-center gap-2 text-[11px] text-foreground/45">
        <span className="truncate rounded border border-outline-variant/45 bg-surface-lowest px-1.5 py-0.5">
          {wing}
        </span>
        <span className="truncate rounded border border-outline-variant/45 bg-surface-lowest px-1.5 py-0.5">
          {room}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="rounded-full border border-emerald-300/40 bg-emerald-500/10 px-2 py-0.5 text-emerald-700 dark:text-emerald-300">
          {summary.status}
        </span>
        <span className="rounded-full border border-outline-variant/45 bg-surface-lowest px-2 py-0.5 text-foreground/55">
          {summary.kind}
        </span>
      </div>
      <h3 className="mt-2 text-sm font-semibold text-foreground/85">{summary.title}</h3>
      <p className="mt-1 text-xs leading-5 text-foreground/75">{summary.summary}</p>
      <p className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/55">{summary.detail}</p>
      <p className="mt-2 truncate text-[11px] text-foreground/40">{source}</p>
    </article>
  );
}

export function MemoryPalacePanel() {
  const [payload, setPayload] = useState<MemoryListPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMemories = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await listMemoryPalaceMemories({ limit: DEFAULT_MEMORY_LIMIT });
      setPayload(result);
    } catch (err) {
      setError(formatEvolutionError(err, '长期记忆读取失败，请稍后重试。'));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchMemories();
  }, [fetchMemories]);

  const memories = payload?.memories ?? [];
  const unavailable = payload !== null && !payload.available;

  return (
    <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-300">
            <BookOpenCheck size={17} />
          </div>
          <div className="min-w-0">
            <h2 className="font-headline text-sm font-semibold text-foreground">长期记忆</h2>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-foreground/55">
              已保存到 MemPalace 的研究经验会在这里显示，便于确认复审结果是否进入长期记忆。
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void fetchMemories()}
          disabled={isLoading}
          className="inline-flex min-h-8 items-center gap-1.5 self-start rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-wait disabled:opacity-60"
          aria-label="刷新长期记忆列表"
        >
          <RefreshCw size={13} className={cn(isLoading && 'animate-spin')} />
          刷新
        </button>
      </div>

      <div className="mt-3">
        {isLoading ? <MemorySkeleton /> : null}

        {!isLoading && error ? (
          <div role="alert" className="rounded-md border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
            {error}
          </div>
        ) : null}

        {!isLoading && !error && unavailable ? (
          <div className="rounded-md border border-outline-variant/45 bg-surface-low px-3 py-4 text-xs leading-5 text-foreground/55">
            长期记忆适配器当前不可用；候选经验仍可先在上方完成复审。
          </div>
        ) : null}

        {!isLoading && !error && !unavailable && memories.length === 0 ? (
          <div className="rounded-md border border-dashed border-outline-variant/50 bg-surface-low px-3 py-4 text-xs leading-5 text-foreground/50">
            暂无长期记忆。保存候选并启用长期记忆应用后，这里会出现最近写入的记忆。
          </div>
        ) : null}

        {!isLoading && !error && !unavailable && memories.length > 0 ? (
          <div className="grid gap-2 md:grid-cols-2">
            {memories.map((memory) => (
              <MemoryCard key={memory.memory_id} memory={memory} />
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
