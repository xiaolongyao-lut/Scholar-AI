// Filters — status + memory_type selectors for the EvolutionInbox.
//
// Two independent callbacks (onStatusChange / onMemoryTypeChange) rather
// than a combined onChange, mirroring ReviewQueuePanel's filter pattern in
// the wiki UI. Page-level state owns the filter values and is responsible
// for resetting `offset` to 0 when either filter changes (covered by
// EvolutionInbox tests in S5.5).
//
// "all" is the sentinel: page maps it to `undefined` before calling
// listCandidates, so the backend's optional filter applies.

import type { CandidateMemoryType, CandidateStatus } from '../../services/evolutionTypes';
import {
  MEMORY_TYPE_LABELS,
  STATUS_LABELS,
} from './labels';

export type StatusFilter = CandidateStatus | 'all';
export type MemoryTypeFilter = CandidateMemoryType | 'all';

export interface FiltersProps {
  status: StatusFilter;
  memoryType: MemoryTypeFilter;
  onStatusChange: (next: StatusFilter) => void;
  onMemoryTypeChange: (next: MemoryTypeFilter) => void;
}

// Surface only the statuses an end user actually navigates between.
// Internal/terminal states (captured/expired/rolled_back) stay accessible
// via the "all" option but are not promoted to top-level chips.
const STATUS_OPTIONS: StatusFilter[] = [
  'pending',
  'accepted',
  'snoozed',
  'rejected',
  'blocked',
  'promoted_to_memory',
  'promoted_to_skill_draft',
  'all',
];

const MEMORY_TYPE_OPTIONS: MemoryTypeFilter[] = [
  'all',
  'user_preference',
  'project_fact',
  'literature_procedure',
  'domain_knowledge',
  'evidence_rule',
  'agent_role_lesson',
  'tool_reliability',
  'skill_draft',
];

function statusLabel(value: StatusFilter): string {
  return value === 'all' ? '全部状态' : STATUS_LABELS[value];
}

function memoryTypeLabel(value: MemoryTypeFilter): string {
  return value === 'all' ? '全部类型' : MEMORY_TYPE_LABELS[value];
}

export function Filters({ status, memoryType, onStatusChange, onMemoryTypeChange }: FiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-outline-variant/40 bg-surface-low px-3 py-2">
      <label className="flex items-center gap-2 text-xs text-foreground/55">
        <span className="font-label tracking-[0.14em] text-foreground/40">状态</span>
        <select
          aria-label="按状态筛选"
          name="evolution-status-filter"
          value={status}
          onChange={(event) => onStatusChange(event.target.value as StatusFilter)}
          className="rounded-md border border-outline-variant/60 bg-surface-high px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/15"
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {statusLabel(option)}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-2 text-xs text-foreground/55">
        <span className="font-label tracking-[0.14em] text-foreground/40">类型</span>
        <select
          aria-label="按经验类型筛选"
          name="evolution-memory-type-filter"
          value={memoryType}
          onChange={(event) => onMemoryTypeChange(event.target.value as MemoryTypeFilter)}
          className="rounded-md border border-outline-variant/60 bg-surface-high px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/15"
        >
          {MEMORY_TYPE_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {memoryTypeLabel(option)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
