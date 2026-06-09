/**
 * MCP Settings section — top-level wrapper introducing the local installer
 * and the advanced manual server form.
 *
 * Tabs:
 *   - 推荐 (McpRecommendedView)
 *   - 本地安装 (McpLocalInstallView) — wizard entry point
 *   - 已安装 (McpInstalledServersView) — list view with approval state
 *   - 高级 (McpAdvancedServerForm) — embeds the legacy CRUD form so
 *     existing manual-entry users keep their workflow.
 *
 * Behavior: tab navigation plus recommended, local install, installed, and
 * advanced manual views.
 */
import React, { useState } from 'react';
import { Server, Sparkles, FolderInput, ListChecks, Wrench } from 'lucide-react';
import { McpRecommendedView } from './McpRecommendedView';
import { McpLocalInstallView } from './McpLocalInstallView';
import { McpInstalledServersView } from './McpInstalledServersView';
import McpServersSectionLegacy from '../McpServersSection';

type McpTabId = 'recommended' | 'local_install' | 'installed' | 'advanced';

interface McpTab {
  id: McpTabId;
  label: string;
  icon: React.ElementType;
  hint?: string;
}

const TABS: McpTab[] = [
  {
    id: 'recommended',
    label: '推荐',
    icon: Sparkles,
    hint: '官方维护的本地可装能力',
  },
  {
    id: 'local_install',
    label: '本地安装',
    icon: FolderInput,
    hint: '从本地目录或压缩包安装第三方 MCP',
  },
  {
    id: 'installed',
    label: '已安装',
    icon: ListChecks,
    hint: '管理已注册的 MCP 服务器',
  },
  {
    id: 'advanced',
    label: '高级 / 手动添加',
    icon: Wrench,
    hint: '直接填写本地启动方式和连接配置',
  },
];

export function McpServersSection(): JSX.Element {
  const [activeTab, setActiveTab] = useState<McpTabId>('recommended');

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <div className="p-1.5 rounded-md bg-primary/10 text-primary mt-0.5">
            <Server size={16} />
          </div>
          <div>
            <h2 className="font-display text-base font-semibold text-foreground">
              MCP 服务器
            </h2>
            <p className="mt-1 font-label text-[11px] leading-relaxed text-foreground/55 max-w-2xl">
              管理本地 MCP 服务。只有「本次会话已授权」的服务才会被对话调用；
              本地进程运行，没有完整沙箱。
            </p>
          </div>
        </div>
      </header>

      <nav
        role="tablist"
        aria-label="MCP 服务器视图"
        className="flex flex-wrap gap-1 border-b border-outline-variant"
      >
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const active = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={active}
              aria-controls={`mcp-panel-${tab.id}`}
              id={`mcp-tab-${tab.id}`}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              title={tab.hint}
              className={[
                'inline-flex items-center gap-1.5 px-3 py-2 -mb-px',
                'font-label text-xs transition-colors',
                'border-b-2 border-transparent',
                active
                  ? 'border-primary text-primary font-medium'
                  : 'text-foreground/55 hover:text-foreground hover:border-outline',
              ].join(' ')}
            >
              <Icon size={13} />
              {tab.label}
            </button>
          );
        })}
      </nav>

      <section
        role="tabpanel"
        id={`mcp-panel-${activeTab}`}
        aria-labelledby={`mcp-tab-${activeTab}`}
      >
        {activeTab === 'recommended' && <McpRecommendedView />}
        {activeTab === 'local_install' && <McpLocalInstallView />}
        {activeTab === 'installed' && <McpInstalledServersView />}
        {activeTab === 'advanced' && (
          <div className="rounded-md border border-outline-variant bg-surface-low p-3">
            <p className="font-label text-[11px] text-foreground/55 mb-3">
              下面的手动表单保留给已经熟悉本地进程或网络服务连接方式的用户。
              新用户建议使用「推荐」或「本地安装」。
            </p>
            <McpServersSectionLegacy />
          </div>
        )}
      </section>
    </div>
  );
}

export default McpServersSection;
