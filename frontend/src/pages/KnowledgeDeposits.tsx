import {
  BookOpenCheck,
  Database,
  GitBranch,
  Layers3,
  Library,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { useMemo } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { PageHeader } from '@/components/common/PageHeader';
import { EvidenceGraphWorkbench } from '@/components/knowledge/EvidenceGraphWorkbench';
import { InsightPoolPanel } from '@/components/knowledge/InsightPoolPanel';
import { KnowledgeLibraryPanel } from '@/components/knowledge/KnowledgeLibraryPanel';
import { SourceVaultPanel } from '@/components/knowledge/SourceVaultPanel';
import { cn } from '@/lib/utils';

type WorkbenchSectionId = 'sources' | 'knowledge' | 'insights' | 'graph';

interface WorkbenchSection {
  id: WorkbenchSectionId;
  path: string;
  label: string;
  detail: string;
  icon: ReactNode;
}

const WORKBENCH_SECTIONS: WorkbenchSection[] = [
  {
    id: 'sources',
    path: '/wiki?section=sources',
    label: '来源库',
    detail: '原文与分块',
    icon: <Database size={16} />,
  },
  {
    id: 'knowledge',
    path: '/wiki?section=knowledge',
    label: '知识库',
    detail: 'Wiki 编译页',
    icon: <Library size={16} />,
  },
  {
    id: 'insights',
    path: '/evolution',
    label: '洞察池',
    detail: '候选经验复审',
    icon: <BookOpenCheck size={16} />,
  },
  {
    id: 'graph',
    path: '/wiki?section=graph',
    label: '证据图谱',
    detail: '可信关系过滤',
    icon: <GitBranch size={16} />,
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
  return 'knowledge';
}

export function KnowledgeDeposits() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const activeSectionId = resolveSectionId(location.pathname, searchParams.get('section'));
  const activeSection = useMemo(
    () => WORKBENCH_SECTIONS.find((section) => section.id === activeSectionId) ?? WORKBENCH_SECTIONS[1],
    [activeSectionId],
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-4 py-4 sm:px-6">
        <PageHeader
          icon={<Layers3 size={18} />}
          title="知识沉淀"
          subtitle="来源、知识、洞察与证据关系在同一个本地工作界面中检索、复审和追溯。"
          className="mb-3"
        />
        <div
          role="tablist"
          aria-label="知识沉淀区段"
          className="grid max-w-5xl grid-cols-2 gap-2 lg:grid-cols-4"
        >
          {WORKBENCH_SECTIONS.map((section) => {
            const selected = section.id === activeSection.id;
            return (
              <button
                key={section.id}
                id={`knowledge-workbench-tab-${section.id}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`knowledge-workbench-panel-${section.id}`}
                onClick={() => {
                  if (!selected) {
                    navigate(section.path);
                  }
                }}
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
      </header>

      <section
        aria-label="知识沉淀当前区段"
        className="min-h-0 flex-1 overflow-auto px-4 py-5 sm:px-6"
      >
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
