import { Navigate, useNavigate } from 'react-router-dom';
import { ArrowLeft, BookMarked, Sparkles } from 'lucide-react';
import { WorkbenchShell } from '@/components/workbench/WorkbenchShell';
import { WikiWorkbench } from '@/pages/WikiWorkbench';
import { Inspiration } from '@/pages/Inspiration';
import { readEnv } from '@/services/env';

function researchWorkbenchFlagEnabled(): boolean {
  return readEnv('VITE_FLAG_RESEARCH_WORKBENCH').toLowerCase() === 'true';
}

export function WorkbenchWiki() {
  if (!researchWorkbenchFlagEnabled()) return <Navigate to="/wiki" replace />;
  return <WorkbenchWikiInner />;
}

function WorkbenchWikiInner() {
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
          <BookMarked size={14} className="shrink-0 text-primary/60" aria-hidden />
          <span className="truncate text-sm font-medium text-foreground">Wiki 工作台</span>
        </>
      }
      canvas={
        <div className="h-full min-h-0 overflow-auto bg-background">
          <WikiWorkbench />
        </div>
      }
      inspector={
        <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3 text-xs text-foreground/75">
          <section className="rounded-md border border-outline-variant/60 bg-surface-low p-3">
            <h3 className="mb-1 text-[11px] font-semibold text-foreground/60">Wiki 工具</h3>
            <p>编译、复审、Doctor 报告与来源材料都在主面板完成。</p>
          </section>
        </div>
      }
      drawer={
        <div className="text-xs text-foreground/55">
          <p>来源材料与冲突列表将随页面切换显示在此抽屉。</p>
        </div>
      }
    />
  );
}

export function WorkbenchInspiration() {
  if (!researchWorkbenchFlagEnabled()) return <Navigate to="/inspiration" replace />;
  return <WorkbenchInspirationInner />;
}

function WorkbenchInspirationInner() {
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
          <Sparkles size={14} className="shrink-0 text-primary/60" aria-hidden />
          <span className="truncate text-sm font-medium text-foreground">灵感思维链</span>
        </>
      }
      canvas={
        <div className="h-full min-h-0 overflow-auto bg-background">
          <Inspiration />
        </div>
      }
      inspector={
        <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3 text-xs text-foreground/75">
          <section className="rounded-md border border-outline-variant/60 bg-surface-low p-3">
            <h3 className="mb-1 text-[11px] font-semibold text-foreground/60">灵感链路</h3>
            <p>生成结果、证据徽章和图谱关系都在主面板完成。</p>
          </section>
        </div>
      }
      drawer={
        <div className="text-xs text-foreground/55">
          <p>每条灵感对应的证据徽章会显示在此抽屉。</p>
        </div>
      }
    />
  );
}
