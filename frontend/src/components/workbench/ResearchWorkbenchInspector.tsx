import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, BookOpen, FileText, MessageSquare, Users2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { type ChatMessageData } from '@/components/chat/Message';
import { Conversation } from '@/components/chat/Conversation';
import { EvidencePill, type EvidenceRefLike } from '@/components/evidence/EvidencePill';
import { DiscussionPanel } from '@/components/DiscussionPanel';
import { listFeatureFlags } from '@/services/featureFlagsApi';

export interface SmartReadStarter {
  id: string;
  label: string;
  /** Optional question filled into the input when this starter is clicked. */
  prompt?: string;
}

interface SmartReadInspectorProps {
  /** Project id forwarded to evidence pills for locator upgrade. */
  projectId?: string | null;
  /** Transcript so far. */
  messages: ChatMessageData[];
  /** Starter suggestions shown in the idle state (§ 18 D2). */
  starters?: SmartReadStarter[];
  /** Called when user sends a message. */
  onSend: (text: string) => void;
  /** True while the active smart-read request is streaming. */
  responding?: boolean;
  /** Cancels the active smart-read request for the current scope. */
  onStop?: () => void;
  /** Branches locally by editing a previous user message. */
  onEditMessage?: (message: ChatMessageData) => void;
  /** Keeps messages through the selected point and starts a fresh branch. */
  onForkMessage?: (message: ChatMessageData) => void;
  /** Called when an evidence pill is selected. */
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidence: EvidenceRefLike) => void;
  navigateEvidenceAfterSelect?: boolean;
  /** Optional context chip strip (e.g. "Selected text" after K1). */
  contextChips?: React.ReactNode;
  /** Optional current-request project reasoning-bias toggle. */
  projectReasoningBias?: {
    enabled: boolean;
    available: boolean;
    loading?: boolean;
    onChange: (enabled: boolean) => void;
  };
}

type InspectorTab = 'smart-read' | 'multi-agent';

interface InspectorProps extends SmartReadInspectorProps {
  /** Multi-Agent inherited context preview shown when MA tab is active. */
  multiAgentContext?: React.ReactNode;
}

/**
 * Right inspector with Smart Read / Multi-Agent tab switch.
 *
 * MC-3: switching tabs preserves the inactive tab's state.
 * § 18 D2: Smart Read idle shows starter suggestion buttons rather than
 * a blank prompt; if backend starter endpoint is unavailable, callers
 * pass static `starters`.
 *
 * Multi-Agent tab defaults to the full discussion workflow. The feature
 * flag remains as a local rollback switch, not as an experimental gate.
 */
export function ResearchWorkbenchInspector({
  projectId,
  messages,
  starters,
  onSend,
  responding = false,
  onStop,
  onEditMessage,
  onForkMessage,
  selectedEvidenceId,
  onSelectEvidence,
  navigateEvidenceAfterSelect = false,
  contextChips,
  projectReasoningBias,
  multiAgentContext,
}: InspectorProps) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<InspectorTab>('smart-read');
  const [embedUnified, setEmbedUnified] = useState(true);
  const [draft, setDraft] = useState('');
  useEffect(() => {
    let cancelled = false;
    listFeatureFlags()
      .then((flags) => {
        if (cancelled) return;
        const entry = flags.find((f) => f.name === 'inspector_embed_unified');
        setEmbedUnified(entry ? Boolean(entry.current) : true);
      })
      .catch(() => {
        if (cancelled) return;
        setEmbedUnified(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const goToDiscussionPage = useCallback(() => {
    const query = projectId ? `?project=${encodeURIComponent(projectId)}` : '';
    navigate(`/discussion${query}`);
  }, [navigate, projectId]);

  const handleEditMessage = useCallback((message: ChatMessageData) => {
    if (message.role !== 'user') return;
    onEditMessage?.(message);
    setDraft(message.content);
  }, [onEditMessage]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Tab switch */}
      <div className="flex shrink-0 items-center gap-1 border-b border-outline-variant/60 bg-surface-low px-2 py-1.5">
        <TabButton active={tab === 'smart-read'} onClick={() => setTab('smart-read')}>
          <BookOpen size={13} /> 智读
        </TabButton>
        <TabButton active={tab === 'multi-agent'} onClick={() => setTab('multi-agent')}>
          <Users2 size={13} /> 多智能体
        </TabButton>
      </div>

      {tab === 'smart-read' ? (
        <Conversation
          messages={messages}
          onSubmit={({ text }) => {
            onSend(text);
            setDraft('');
          }}
          projectId={projectId}
          inputValue={draft}
          onInputValueChange={setDraft}
          disabled={responding}
          responding={responding}
          onStop={onStop}
          onEditMessage={handleEditMessage}
          onForkMessage={onForkMessage}
          selectedEvidenceId={selectedEvidenceId}
          onSelectEvidence={onSelectEvidence}
          navigateEvidenceAfterSelect={navigateEvidenceAfterSelect}
          placeholder="提出关于本文的问题或高亮一段文字"
          composerHint="提示：按 Ctrl/Cmd + Enter 快速发送"
          projectReasoningBias={projectReasoningBias}
          contextChips={contextChips}
          emptyState={
            <SmartReadEmpty
              starters={starters ?? DEFAULT_STARTERS}
              onPick={(s) => onSend(s.prompt ?? s.label)}
            />
          }
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3 text-sm">
          {embedUnified ? (
            <>
              {multiAgentContext ? <div className="shrink-0">{multiAgentContext}</div> : null}
              <div className="min-h-[560px] flex-1">
                <DiscussionPanel defaults={INSPECTOR_DISCUSSION_DEFAULTS} />
              </div>
            </>
          ) : (
            <InspectorDiscussionFallback
              context={multiAgentContext}
              onGoToDiscussionPage={goToDiscussionPage}
            />
          )}
        </div>
      )}
    </div>
  );
}

const INSPECTOR_DISCUSSION_DEFAULTS = {
  auto_stop: true,
  min_turns: 2,
} as const;

function InspectorDiscussionFallback({
  context,
  onGoToDiscussionPage,
}: {
  context?: React.ReactNode;
  onGoToDiscussionPage: () => void;
}) {
  return (
    <>
      {context ? <div className="shrink-0">{context}</div> : null}
      <div className="rounded-md border border-dashed border-outline-variant bg-surface-low p-4 text-xs text-foreground/55">
        <p className="mb-2 font-medium text-foreground/75">多智能体讨论已切换到回退入口</p>
        <p className="mb-3 leading-relaxed">
          内嵌讨论已关闭。
        </p>
        <button
          type="button"
          onClick={onGoToDiscussionPage}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          前往多智能体讨论页
          <ArrowRight size={12} />
        </button>
      </div>
    </>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      role="tab"
      aria-selected={active}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-sm px-2 py-1 text-xs font-medium transition-colors',
        active ? 'bg-surface-lowest text-foreground shadow-sm' : 'text-foreground/55 hover:bg-surface-default/60 hover:text-foreground',
      )}
    >
      {children}
    </button>
  );
}

function SmartReadEmpty({ starters, onPick }: { starters: SmartReadStarter[]; onPick: (s: SmartReadStarter) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-2 py-8 text-center">
      <FileText size={28} className="text-foreground/30" aria-hidden />
      <p className="text-sm text-foreground/55">提出关于本文的问题，或高亮一段文字让我帮你解读</p>
      {starters.length > 0 && (
        <div className="flex w-full flex-col gap-2">
          {starters.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => onPick(s)}
              className="rounded-md border border-outline-variant/70 bg-surface-low px-3 py-2 text-left text-xs text-foreground/75 transition-colors hover:border-primary/60 hover:bg-primary/5 hover:text-foreground"
            >
              <MessageSquare size={11} className="mr-1 inline-block opacity-60" aria-hidden /> {s.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const DEFAULT_STARTERS: SmartReadStarter[] = [
  { id: 'summary', label: '总结这篇论文的核心贡献', prompt: '请用三句话总结这篇论文的核心贡献。' },
  { id: 'method', label: '解释主要方法' , prompt: '请解释这篇论文的主要方法和关键思路。' },
  { id: 'limitations', label: '讨论局限性与未来工作', prompt: '这篇论文有哪些局限性？后续可以怎么扩展？' },
];

export function ResearchWorkbenchEvidenceDrawer({
  evidence,
  projectId,
  selectedEvidenceId,
  onSelectEvidence,
  navigateEvidenceAfterSelect = false,
}: {
  evidence: EvidenceRefLike[];
  projectId?: string | null;
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidence: EvidenceRefLike) => void;
  navigateEvidenceAfterSelect?: boolean;
}) {
  if (!evidence || evidence.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-foreground/45">
        <FileText size={20} className="text-foreground/30" aria-hidden />
        <p>暂无证据，提问或高亮一段文字后将出现在这里</p>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {evidence.map((ev, i) => (
        <EvidencePill
          key={`${ev.evidence_id ?? ev.chunk_id ?? '_'}:${i}`}
          evidence={ev}
          projectId={projectId}
          selected={
            !!selectedEvidenceId &&
            (ev.evidence_id === selectedEvidenceId || ev.chunk_id === selectedEvidenceId)
          }
          onActivate={onSelectEvidence}
          navigateAfterActivate={navigateEvidenceAfterSelect}
        />
      ))}
    </div>
  );
}
