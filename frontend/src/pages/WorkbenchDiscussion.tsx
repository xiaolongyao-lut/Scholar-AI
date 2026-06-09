import { Navigate } from 'react-router-dom';
import { ArrowLeft, MessageSquare, Users2, Activity } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { WorkbenchShell } from '@/components/workbench/WorkbenchShell';
import { DiscussionPanel } from '@/components/DiscussionPanel';

/**
 * Discussion as a first-class Workbench object.
 *
 * Route: `/workbench/discussion`
 * Behind `VITE_FLAG_RESEARCH_WORKBENCH` — same gate as the Paper
 * object. When the flag is off, redirects to legacy `/discussion`.
 *
 * v1 constraints (per IA plan L10 G1 lock):
 *   - Agent-only: NO transcript composer is rendered. The existing
 *     DiscussionPanel surfaces start/stop and roster controls; the
 *     Workbench shell does not add any human-in-the-loop composer.
 *   - Stop / Manual nudge / Auto-stop / Agent roster live in the
 *     right inspector (kept inside DiscussionPanel for now; richer
 *     inspector surface lands in a later phase).
 *
 * Backend boundary (Q1 = strict): no inherited_context payload is
 * sent. The frontend can package it client-side; the existing
 * /api/discussion/runs endpoint is untouched.
 */
export function WorkbenchDiscussion() {
  const flagEnabled = String(import.meta.env.VITE_FLAG_RESEARCH_WORKBENCH ?? '').toLowerCase() === 'true';
  if (!flagEnabled) return <Navigate to="/discussion" replace />;

  return <WorkbenchDiscussionInner />;
}

function WorkbenchDiscussionInner() {
  const navigate = useNavigate();

  return (
    <WorkbenchShell
      drawerTitle="证据抽屉"
      header={
        <>
          <button
            type="button"
            onClick={() => navigate('/library')}
            className="flex shrink-0 items-center gap-1 rounded p-1 text-foreground/60 hover:bg-surface-high hover:text-foreground"
            title="返回文献库"
            aria-label="返回文献库"
          >
            <ArrowLeft size={14} />
          </button>
          <MessageSquare size={14} className="shrink-0 text-primary/60" aria-hidden />
          <span className="truncate text-sm font-medium text-foreground">多智能体讨论</span>
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-outline-variant bg-surface-low px-1.5 py-0.5 text-[10px] font-medium text-foreground/65">
            <Activity size={10} aria-hidden /> 工作台模式
          </span>
        </>
      }
      canvas={
        <div className="h-full min-h-0 overflow-auto bg-background">
          <DiscussionPanel onInsertToEditor={() => { /* v1 agent-only — no editor handoff */ }} />
        </div>
      }
      inspector={
        <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3 text-xs text-foreground/75">
          <section className="rounded-md border border-outline-variant/60 bg-surface-low p-3">
            <h3 className="mb-1 text-[11px] font-semibold text-foreground/60">运行控制</h3>
            <p>开始、停止和自动停止都在左侧讨论面板顶部完成。</p>
          </section>
          <section className="rounded-md border border-outline-variant/60 bg-surface-low p-3">
            <h3 className="mb-1 text-[11px] font-semibold text-foreground/60">证据</h3>
            <p>引用与证据片段会出现在底部抽屉。</p>
          </section>
        </div>
      }
      drawer={
        <div className="text-xs text-foreground/55">
          <p>引用与证据将在讨论运行后显示在此处。</p>
        </div>
      }
    />
  );
}

export default WorkbenchDiscussion;
