import React, { useState, useCallback, useEffect } from 'react';
import { DiscussionPanel } from '@/components/DiscussionPanel';
import { useToast } from '@/components/ui/Toast';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import {
  type DiscussionDefaults,
  DEFAULT_DISCUSSION_DEFAULTS,
  normalizeDiscussionDefaults,
} from '@/services/discussionDefaults';
import { CheckCircle2, FileText, Loader2, MessageSquare, Users2 } from 'lucide-react';
import axios from 'axios';
import { PageHeader } from '@/components/common/PageHeader';
import { StatusPill } from '@/components/common/StatusPill';
import { SectionCard } from '@/components/common/SectionCard';

type DefaultsLoadState = 'loading' | 'ready' | 'fallback';

/**
 * Discussion page.
 *
 * Visual reference:
 *   - `07_object_surfaces/09_discussion_object_active.png` (object header pattern)
 *   - `03_multi_agent/04_multi_agent_ready.png` (right inspector layout)
 *   - `03_multi_agent/03_multi_agent_running_regen.png` (running state pills)
 *
 * Constraints honored:
 *   - L10 G1 (v1 agent-only): no transcript human-in-the-loop composer.
 *     DiscussionPanel only renders the setup form + agent transcript;
 *     we do not add a "Type a message to the discussion" composer.
 *   - R5 / R5.1: Chinese-only; no raw IDs.
 *   - MC-4 single focus accent; status pills via canonical `StatusPill`.
 */
export const Discussion: React.FC = () => {
  const { toast } = useToast();
  const [editorContent, setEditorContent] = useState<string>('');
  const [defaults, setDefaults] = useState<DiscussionDefaults>({ ...DEFAULT_DISCUSSION_DEFAULTS });
  const [defaultsState, setDefaultsState] = useState<DefaultsLoadState>('loading');

  useEffect(() => {
    const loadDefaults = async () => {
      try {
        const { data } = await axios.get<unknown>(`${getApiBaseUrl()}/api/discussion/defaults`);
        setDefaults(normalizeDiscussionDefaults(data));
        setDefaultsState('ready');
      } catch {
        setDefaultsState('fallback');
      }
    };
    void loadDefaults();
  }, []);

  const handleInsertToEditor = useCallback(
    (content: string) => {
      setEditorContent((prev) => `${prev}\n\n${content}`);
      toast('已插入讨论结论', 'success');
    },
    [toast],
  );

  const previewLength = editorContent.trim().length;
  const defaultsTone = defaultsState === 'loading' ? 'neutral' : defaultsState === 'ready' ? 'success' : 'warning';
  const defaultsLabel =
    defaultsState === 'loading' ? '默认值加载中' : defaultsState === 'ready' ? '默认值已同步' : '使用本地默认值';

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<Users2 size={18} />}
          title="多智能体讨论"
          subtitle="让多位 AI 智能体围绕同一研究问题进行结构化讨论"
          className="mb-0"
          actions={
            defaultsState === 'loading' ? (
              <StatusPill tone="neutral" icon={<Loader2 size={10} className="animate-spin" />}>
                正在加载默认配置
              </StatusPill>
            ) : previewLength > 0 ? (
              <StatusPill tone="primary" title="已插入字符数">
                已插入 {previewLength} 字
              </StatusPill>
            ) : null
          }
        />
      </div>

      <div className="min-h-0 flex-1 overflow-hidden p-6">
        <div className="grid h-full grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          {/* Left: shipped DiscussionPanel hosts the setup + transcript */}
          <div className="min-h-0 overflow-auto">
            <DiscussionPanel onInsertToEditor={handleInsertToEditor} defaults={defaults} />
          </div>

          {/* Right: insertion preview + scope notice */}
          <div className="flex min-h-0 flex-col gap-4">
            <SectionCard
              title="讨论结论预览"
              icon={<MessageSquare size={14} />}
              subtitle="插入写作区后会保留完整换行；可继续追加多段结论"
              headerRight={
                <StatusPill tone="neutral" title="字符数">
                  {previewLength} 字
                </StatusPill>
              }
              className="min-h-0 flex-1"
              bodyClassName="h-full overflow-auto"
            >
              {editorContent ? (
                <pre className="whitespace-pre-wrap rounded-md bg-surface-low px-4 py-3 text-sm leading-relaxed text-foreground/80">
                  {editorContent}
                </pre>
              ) : (
                <div className="flex h-full flex-col items-center justify-center text-center">
                  <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-md border border-dashed border-outline-variant bg-surface-low">
                    <FileText size={18} className="text-foreground/35" />
                  </div>
                  <p className="text-sm font-medium text-foreground/65">讨论结论将显示在这里</p>
                  <p className="mt-1 max-w-xs text-xs leading-relaxed text-foreground/45">
                    运行讨论并将综合结论插入写作区后，本面板会同步预览。
                  </p>
                </div>
              )}
            </SectionCard>

          </div>
        </div>
      </div>
    </div>
  );
};

export default Discussion;
