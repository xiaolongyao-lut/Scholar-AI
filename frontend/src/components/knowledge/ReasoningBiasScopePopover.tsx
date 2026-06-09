import { Bot, BrainCircuit, MessagesSquare, Network } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ProjectReasoningBiasScopes } from '@/types/resources';

interface ReasoningBiasScopePopoverProps {
  scopes: ProjectReasoningBiasScopes;
  onChange: (scopes: ProjectReasoningBiasScopes) => void;
  disabled?: boolean;
}

type ScopeKey = 'analysis_chain' | 'chat_generation' | 'project_wide';

const scopeRows: Array<{
  key: ScopeKey;
  label: string;
  description: string;
  icon: typeof BrainCircuit;
}> = [
  {
    key: 'analysis_chain',
    label: '思维链',
    description: '影响 AI 如何组织观察、证据、反证和下一步思考',
    icon: BrainCircuit,
  },
  {
    key: 'chat_generation',
    label: '聊天与生成',
    description: '影响智能研读、写作生成和引用建议',
    icon: MessagesSquare,
  },
  {
    key: 'project_wide',
    label: '全项目',
    description: '所有已登记的 AI 功能默认受影响',
    icon: Network,
  },
];

export function ReasoningBiasScopePopover({
  scopes,
  onChange,
  disabled = false,
}: ReasoningBiasScopePopoverProps) {
  const updateScope = (key: ScopeKey, value: boolean) => {
    onChange({ ...scopes, [key]: value });
  };
  const agentText = scopes.discussion_agent_ids.join(', ');

  return (
    <div className="grid gap-2 rounded-md border border-outline-variant/60 bg-surface-lowest p-2 text-xs shadow-sm md:grid-cols-2 xl:grid-cols-4">
      {scopeRows.map(({ key, label, description, icon: Icon }) => (
        <label
          key={key}
          className={cn(
            'flex min-h-[76px] cursor-pointer items-start gap-2 rounded-md border border-outline-variant/50 bg-surface-low px-2.5 py-2 transition-colors',
            scopes[key] ? 'border-primary/50 bg-primary/10' : 'hover:border-primary/35',
            disabled && 'cursor-not-allowed opacity-60',
          )}
        >
          <input
            type="checkbox"
            aria-label={label}
            className="mt-0.5 h-4 w-4 rounded border-outline-variant"
            checked={scopes[key]}
            disabled={disabled}
            onChange={(event) => updateScope(key, event.target.checked)}
          />
          <span className="min-w-0">
            <span className="flex items-center gap-1.5 font-medium text-foreground">
              <Icon size={13} className="text-primary/70" />
              {label}
            </span>
            <span className="mt-1 block leading-5 text-foreground/55">{description}</span>
          </span>
        </label>
      ))}

      <div
        className={cn(
          'min-h-[76px] rounded-md border border-outline-variant/50 bg-surface-low px-2.5 py-2',
          scopes.discussion_agent_ids.length > 0 && 'border-primary/50 bg-primary/10',
        )}
      >
        <div className="flex items-center gap-1.5 font-medium text-foreground">
          <Bot size={13} className="text-primary/70" />
          指定讨论智能体
        </div>
        <input
          type="text"
          aria-label="讨论角色 ID"
          value={agentText}
          disabled={disabled}
          onChange={(event) => {
            const normalized = event.target.value
              .split(/[,\uFF0C]/)
              .map((item) => item.trim())
              .filter((item, index, list) => item.length > 0 && list.indexOf(item) === index)
              .slice(0, 16);
            onChange({ ...scopes, discussion_agent_ids: normalized });
          }}
          placeholder="proposer, critic 或 proposer，critic"
          className="mt-1 w-full rounded border border-outline-variant/60 bg-surface-lowest px-2 py-1 text-[11px] text-foreground placeholder:text-foreground/35 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/20 disabled:opacity-60"
        />
        <p className="mt-1 break-words text-[11px] leading-5 text-foreground/45">
          填设置页“角色与 API”详情里的“讨论角色 ID”，例如 proposer, critic 或 proposer，critic；英文逗号 , 和中文逗号 ， 都可以。这里不是角色显示名称。
        </p>
      </div>
    </div>
  );
}
