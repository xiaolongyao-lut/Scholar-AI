/** Recommended MCP capability cards wired to the install wizard. */
import React, { useState } from 'react';
import { Image as ImageIcon, Paintbrush, Search, FolderInput } from 'lucide-react';
import McpInstallWizard from './McpInstallWizard';
import { clearWizardState, loadWizardState } from './wizardState';

interface RecommendedCapability {
  id: string;
  display_name: string;
  description: string;
  icon: React.ElementType;
}

const RECOMMENDED: RecommendedCapability[] = [
  {
    id: 'vision-auxiliary',
    display_name: '视觉辅助',
    description: '让纯文本聊天模型能处理图片输入。',
    icon: ImageIcon,
  },
  {
    id: 'image-gen',
    display_name: 'AI 生图',
    description: '通过你配置的图像模型生成插图。',
    icon: Paintbrush,
  },
  {
    id: 'web-search',
    display_name: '网络搜索',
    description: 'DuckDuckGo / Tavily 搜索接入。',
    icon: Search,
  },
];

interface WizardOpenState {
  open: boolean;
  initialPath: string;
  templateHint?: string;
  presetSlug?: string;
  presetDisplayName?: string;
}

export function McpRecommendedView(): JSX.Element {
  const [wizard, setWizard] = useState<WizardOpenState>(() => {
    const restored = loadWizardState();
    if (restored) {
      return {
        open: true,
        initialPath: restored.source_path,
        templateHint: restored.template_hint,
        presetSlug: restored.server_slug,
        presetDisplayName: restored.display_name,
      };
    }
    return { open: false, initialPath: '' };
  });

  const openWizard = (cap: RecommendedCapability) => {
    clearWizardState();
    setWizard({
      open: false,
      initialPath: '',
      templateHint: cap.id,
      presetSlug: cap.id.replace(/-/g, '_'),
      presetDisplayName: cap.display_name,
    });
    window.setTimeout(() => {
      setWizard({
        open: true,
        initialPath: '',
        templateHint: cap.id,
        presetSlug: cap.id.replace(/-/g, '_'),
        presetDisplayName: cap.display_name,
      });
    }, 0);
  };

  return (
    <div className="space-y-3">
      <p className="font-label text-[11px] text-foreground/55">
        以下是文献助手官方推荐的本地可装能力。请先自行下载或克隆对应仓库到本地,
        再用一键安装将其注册到当前主机。安装过程**不会**联网下载,也不会执行任何包代码(除非你勾选探测)。
      </p>

      <ul className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {RECOMMENDED.map((cap) => {
          const Icon = cap.icon;
          return (
            <li
              key={cap.id}
              className="rounded-md border border-outline-variant bg-surface-low p-3 flex items-start gap-3"
            >
              <div className="p-2 rounded-md bg-primary/10 text-primary mt-0.5 flex-shrink-0">
                <Icon size={14} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="font-display text-sm font-semibold text-foreground">
                    {cap.display_name}
                  </h3>
                </div>
                <p className="mt-1 font-label text-[11px] text-foreground/55">{cap.description}</p>
                <p className="mt-2 font-label text-[10px] text-foreground/40">
                  在向导中选择你已经下载到本机的对应 MCP 包目录。
                </p>
                <button
                  type="button"
                  onClick={() => openWizard(cap)}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-3 py-1.5 font-label text-xs font-medium text-primary hover:bg-primary/15"
                >
                  <FolderInput size={12} /> 选择本地包并安装
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      <McpInstallWizard
        key={`${wizard.open ? 'open' : 'closed'}:${wizard.templateHint ?? 'manual'}:${wizard.initialPath}`}
        open={wizard.open}
        initialPath={wizard.initialPath}
        templateHint={wizard.templateHint}
        presetSlug={wizard.presetSlug}
        presetDisplayName={wizard.presetDisplayName}
        onClose={() => setWizard({ ...wizard, open: false })}
      />
    </div>
  );
}

export default McpRecommendedView;
