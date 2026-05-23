import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, BookOpen, FileText, MessageSquare, Users2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Message, type ChatMessageData } from '@/components/chat/Message';
import { EvidencePill, type EvidenceRefLike } from '@/components/evidence/EvidencePill';

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
  /** Called when an evidence pill is selected (Slice 3 selection-bus glue). */
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidence: EvidenceRefLike) => void;
  /** Optional context chip strip (e.g. "Selected text" after K1). */
  contextChips?: React.ReactNode;
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
 * Multi-Agent tab in v1 is a context-preview placeholder (Slice 3);
 * Slice 4 wires real Discussion-object-derived controls. Per L10 G1,
 * no human-in-the-loop composer is rendered here in v1.
 */
export function ResearchWorkbenchInspector({
  projectId,
  messages,
  starters,
  onSend,
  selectedEvidenceId,
  onSelectEvidence,
  contextChips,
  multiAgentContext,
}: InspectorProps) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<InspectorTab>('smart-read');
  const [draft, setDraft] = useState('');

  const handleSend = useCallback(() => {
    const text = draft.trim();
    if (!text) return;
    onSend(text);
    setDraft('');
  }, [draft, onSend]);

  const goToDiscussionPage = useCallback(() => {
    const query = projectId ? `?project=${encodeURIComponent(projectId)}` : '';
    navigate(`/discussion${query}`);
  }, [navigate, projectId]);

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
        <div className="flex min-h-0 flex-1 flex-col">
          {contextChips && (
            <div className="shrink-0 border-b border-outline-variant/40 px-3 py-2">{contextChips}</div>
          )}

          <div className="min-h-0 flex-1 space-y-3 overflow-auto px-3 py-3">
            {messages.length === 0 ? (
              <SmartReadEmpty starters={starters ?? DEFAULT_STARTERS} onPick={(s) => onSend(s.prompt ?? s.label)} />
            ) : (
              messages.map((m) => (
                <Message
                  key={m.id}
                  message={m}
                  projectId={projectId}
                  selectedEvidenceId={selectedEvidenceId}
                  onSelectEvidence={onSelectEvidence}
                />
              ))
            )}
          </div>

          <div className="shrink-0 border-t border-outline-variant/60 bg-surface-low p-2">
            <div className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                rows={2}
                placeholder="提出关于本文的问题或高亮一段文字"
                className="min-h-[44px] flex-1 resize-none rounded-md border border-outline-variant/60 bg-surface-lowest px-2 py-1.5 text-sm text-foreground placeholder:text-foreground/35 focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <button
                type="button"
                onClick={handleSend}
                disabled={!draft.trim()}
                className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                发送
              </button>
            </div>
            <p className="mt-1 text-[10px] text-foreground/40">提示：按 Ctrl/Cmd + Enter 快速发送</p>
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3 text-sm">
          {multiAgentContext ?? (
            <div className="rounded-md border border-dashed border-outline-variant bg-surface-low p-4 text-xs text-foreground/55">
              <p className="mb-2 font-medium text-foreground/75">还没有多智能体讨论</p>
              <p className="mb-3 leading-relaxed">这里会显示围绕当前 PDF 上下文的多智能体讨论。开始一轮新讨论的方式：</p>
              <ul className="mb-3 ml-4 list-disc space-y-1 leading-relaxed">
                <li>选中 PDF 文段后，在弹出的工具条上点「多智能体」（推荐，自动携带选区作为讨论上下文）</li>
                <li>或前往多智能体讨论页，手动设置角色与证据</li>
              </ul>
              <button
                type="button"
                onClick={goToDiscussionPage}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                前往多智能体讨论页
                <ArrowRight size={12} />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
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
}: {
  evidence: EvidenceRefLike[];
  projectId?: string | null;
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidence: EvidenceRefLike) => void;
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
        />
      ))}
    </div>
  );
}
