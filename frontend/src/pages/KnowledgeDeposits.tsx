import {
  ChevronDown,
  Database,
  GitBranch,
  Inbox,
  Layers3,
  Library,
  Search,
  Sparkles,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { PageHeader } from '@/components/common/PageHeader';
import { EvidenceGraphWorkbench } from '@/components/knowledge/EvidenceGraphWorkbench';
import { CaptureToInboxButton } from '@/components/knowledge/CaptureToInboxButton';
import { InsightPoolPanel } from '@/components/knowledge/InsightPoolPanel';
import { KnowledgePackagesPanel } from '@/components/knowledge/KnowledgePackagesPanel';
import { KnowledgeLibraryPanel } from '@/components/knowledge/KnowledgeLibraryPanel';
import { SourceVaultPanel } from '@/components/knowledge/SourceVaultPanel';
import { cn } from '@/lib/utils';

// 记忆流外壳：四个步骤映射到既有面板，不重写底层功能。
// 待确认 = InsightPoolPanel (EvolutionInbox + Wiki review 入口)
// 已沉淀 = KnowledgeLibraryPanel (WikiWorkbench embedded)
// 来源   = SourceVaultPanel (原文与分块)
// 关联   = EvidenceGraphWorkbench (证据图谱)
type WorkbenchSectionId = 'sources' | 'knowledge' | 'insights' | 'graph';

interface WorkbenchSection {
  id: WorkbenchSectionId;
  /** ?section= 兼容值，保持与旧链接一致 */
  param: string;
  /** 旧版四等分入口的路由路径，保留向后兼容 */
  path: string;
  /** 新流程中的产品语义标签 */
  label: string;
  /** 旧版工程语义标签，仅在「高级 / 诊断」展开时复现 */
  legacyLabel: string;
  /** 主流程描述 */
  detail: string;
  /** 高级折叠中展示的工程描述 */
  advancedDetail: string;
  icon: ReactNode;
  /** 主流程是否常驻：true=主三步，false=高级里再出现 */
  primary: boolean;
}

const WORKBENCH_SECTIONS: WorkbenchSection[] = [
  {
    id: 'insights',
    param: 'insights',
    path: '/evolution',
    label: '待确认',
    legacyLabel: '洞察池',
    detail: '待复审内容',
    advancedDetail: '候选经验复审',
    icon: <Inbox size={16} />,
    primary: true,
  },
  {
    id: 'knowledge',
    param: 'knowledge',
    path: '/wiki?section=knowledge',
    label: '已沉淀',
    legacyLabel: '知识库',
    detail: '已确认页面',
    advancedDetail: 'Wiki 编译页',
    icon: <Library size={16} />,
    primary: true,
  },
  {
    id: 'sources',
    param: 'sources',
    path: '/wiki?section=sources',
    label: '来源',
    legacyLabel: '来源库',
    detail: '原文与分块',
    advancedDetail: '原文与分块',
    icon: <Database size={16} />,
    primary: false,
  },
  {
    id: 'graph',
    param: 'graph',
    path: '/wiki?section=graph',
    label: '关联',
    legacyLabel: '证据图谱',
    detail: '关系视图',
    advancedDetail: '可信关系过滤',
    icon: <GitBranch size={16} />,
    primary: false,
  },
];

function isWorkbenchSectionId(value: string | null): value is WorkbenchSectionId {
  return value === 'sources' || value === 'knowledge' || value === 'insights' || value === 'graph';
}

function resolveSectionId(pathname: string, sectionParam: string | null): WorkbenchSectionId {
  if (pathname.startsWith('/evolution')) {
    return 'insights';
  }
  if (isWorkbenchSectionId(sectionParam)) {
    return sectionParam;
  }
  // 新默认：进入待确认收件箱，符合「记一下 → 待确认 → 沉淀」记忆流。
  return 'insights';
}

export function KnowledgeDeposits() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const activeSectionId = resolveSectionId(location.pathname, searchParams.get('section'));
  const activeSection = useMemo(
    () => WORKBENCH_SECTIONS.find((section) => section.id === activeSectionId) ?? WORKBENCH_SECTIONS[0],
    [activeSectionId],
  );
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // 切到高级区段时自动展开折叠面板，避免出现「点了 tab 看不到内容」。
  useEffect(() => {
    if (!activeSection.primary) {
      setAdvancedOpen(true);
    }
  }, [activeSection.primary, activeSection.id]);

  const navigateToSection = (section: WorkbenchSection) => {
    if (section.id === activeSection.id) return;
    navigate(section.path);
  };

  const primarySections = WORKBENCH_SECTIONS.filter((section) => section.primary);
  const advancedSections = WORKBENCH_SECTIONS.filter((section) => !section.primary);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-4 py-4 sm:px-6">
        <PageHeader
          icon={<Layers3 size={18} />}
          title="知识沉淀"
          subtitle="记录、复审、沉淀、召回。"
          className="mb-3"
        />

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <CaptureToInboxButton
            label="记一下"
            className="border-primary bg-primary px-3 py-1.5 text-primary-foreground hover:bg-primary/90"
            context={{
              kind: 'generic',
              sourceLabel: '知识沉淀',
            }}
          />
          <button
            type="button"
            onClick={() => navigate('/wiki?section=insights')}
            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 text-xs text-foreground/75 transition-colors hover:border-primary/35 hover:text-primary"
          >
            <Inbox size={13} />
            查看待确认
          </button>
          <button
            type="button"
            onClick={() => navigate('/wiki?section=knowledge')}
            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 text-xs text-foreground/75 transition-colors hover:border-primary/35 hover:text-primary"
          >
            <Search size={13} />
            写作时检索
          </button>
          <div className="ml-auto flex flex-wrap items-center gap-1.5 text-[11px] text-foreground/55">
            <Sparkles size={12} className="text-primary/70" />
            <span>默认进待确认</span>
          </div>
        </div>

        <div
          role="tablist"
          aria-label="知识沉淀主流程"
          className="grid max-w-5xl grid-cols-2 gap-2 lg:grid-cols-3"
        >
          {primarySections.map((section) => {
            const selected = section.id === activeSection.id;
            return (
              <button
                key={section.id}
                id={`knowledge-workbench-tab-${section.id}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`knowledge-workbench-panel-${section.id}`}
                onClick={() => navigateToSection(section)}
                className={cn(
                  'flex min-h-[3.25rem] min-w-0 items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors',
                  selected
                    ? 'border-primary/45 bg-primary/10 text-primary shadow-sm'
                    : 'border-outline-variant/60 bg-surface-lowest text-foreground/60 hover:border-primary/30 hover:text-foreground',
                )}
              >
                <span className={cn('shrink-0', selected ? 'text-primary' : 'text-foreground/45')}>
                  {section.icon}
                </span>
                <span className="min-w-0">
                  <span className="block truncate font-label text-sm font-semibold">{section.label}</span>
                  <span className="block truncate text-[11px] text-foreground/45">{section.detail}</span>
                </span>
              </button>
            );
          })}
        </div>

        <details
          className="mt-3 rounded-md border border-outline-variant/50 bg-surface-lowest"
          open={advancedOpen}
          onToggle={(event) => setAdvancedOpen((event.currentTarget as HTMLDetailsElement).open)}
        >
          <summary className="flex cursor-pointer items-center justify-between px-3 py-2 text-[11px] text-foreground/60 marker:hidden">
            <span className="inline-flex items-center gap-1.5">
              <ChevronDown size={12} className={cn('transition-transform', advancedOpen ? 'rotate-0' : '-rotate-90')} />
              高级 / 诊断
            </span>
            <span className="text-foreground/40">来源、图谱、诊断、导出</span>
          </summary>
          <div
            role="tablist"
            aria-label="知识沉淀高级区段"
            className="grid gap-2 px-3 pb-3 pt-2 sm:grid-cols-2"
          >
            {advancedSections.map((section) => {
              const selected = section.id === activeSection.id;
              return (
                <button
                  key={section.id}
                  id={`knowledge-workbench-tab-${section.id}`}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls={`knowledge-workbench-panel-${section.id}`}
                  onClick={() => navigateToSection(section)}
                  className={cn(
                    'flex min-h-[3rem] min-w-0 items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors',
                    selected
                      ? 'border-primary/45 bg-primary/10 text-primary'
                      : 'border-outline-variant/50 bg-surface-low text-foreground/60 hover:border-primary/30 hover:text-foreground',
                  )}
                >
                  <span className={cn('shrink-0', selected ? 'text-primary' : 'text-foreground/45')}>
                    {section.icon}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-label text-sm font-semibold">
                      {section.label}
                    </span>
                    <span className="block truncate text-[11px] text-foreground/45">{section.advancedDetail}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </details>
      </header>

      <section
        aria-label="知识沉淀当前区段"
        className="min-h-0 flex-1 overflow-auto px-4 py-5 sm:px-6"
      >
        <div className="mx-auto mb-4 max-w-7xl">
          <KnowledgePackagesPanel />
        </div>
        <div
          id={`knowledge-workbench-panel-${activeSection.id}`}
          role="tabpanel"
          aria-labelledby={`knowledge-workbench-tab-${activeSection.id}`}
          className="mx-auto max-w-7xl"
        >
          {activeSection.id === 'sources' ? <SourceVaultPanel /> : null}
          {activeSection.id === 'knowledge' ? <KnowledgeLibraryPanel /> : null}
          {activeSection.id === 'insights' ? <InsightPoolPanel /> : null}
          {activeSection.id === 'graph' ? <EvidenceGraphWorkbench /> : null}
        </div>
      </section>

      <div className="sr-only" aria-live="polite">
        当前区段：{activeSection.label}
      </div>
    </div>
  );
}

export default KnowledgeDeposits;

export const __knowledgeWorkbenchSectionsForTests = WORKBENCH_SECTIONS;
export const __resolveKnowledgeWorkbenchSectionForTests = resolveSectionId;
