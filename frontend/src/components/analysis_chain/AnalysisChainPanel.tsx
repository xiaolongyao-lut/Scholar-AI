import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import type { AnalysisChainPayload } from '@/services/discussionApi';
import { EvidencePill, type EvidenceRefLike } from '@/components/evidence/EvidencePill';

/**
 * Shared collapsible renderer for a 6-field AnalysisChain.
 *
 * Used by DiscussionPanel (per-agent), SmartRead messages, and (future)
 * Workbench sources panel. Renders nothing when the chain has no
 * meaningful content so callers can pass partial chains without
 * conditional rendering on their side.
 */

interface AnalysisChainPanelProps {
  chain: AnalysisChainPayload | null | undefined;
  /** Compact 4-line header when collapsed; expand for full 6 fields. */
  defaultExpanded?: boolean;
  /** Controlled expansion state for parent-owned trace selection. */
  expanded?: boolean;
  /** Called when the user toggles the panel in controlled mode. */
  onExpandedChange?: (expanded: boolean) => void;
  /** User-visible title for surfaces that need more precise wording. */
  title?: string;
  /** Wrapper class — caller controls outer spacing/borders. */
  className?: string;
  /** Active project id forwarded to evidence pills for locator upgrade. */
  projectId?: string | null;
  /** Selection bus glue — focused evidence id (chunk_id / evidence_id). */
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidence: EvidenceRefLike) => void;
  navigateEvidenceAfterSelect?: boolean;
}

function _hasContent(chain: AnalysisChainPayload): boolean {
  return Boolean(
    (chain.observation && chain.observation.trim()) ||
      (chain.mechanism && chain.mechanism.trim()) ||
      (chain.evidence && chain.evidence.length > 0) ||
      (chain.boundary && chain.boundary.trim()) ||
      (chain.counter_evidence && chain.counter_evidence.length > 0) ||
      (chain.next_action && chain.next_action.trim()),
  );
}

export function AnalysisChainPanel({
  chain,
  defaultExpanded = false,
  expanded,
  onExpandedChange,
  title,
  className,
  projectId,
  selectedEvidenceId,
  onSelectEvidence,
  navigateEvidenceAfterSelect = false,
}: AnalysisChainPanelProps) {
  const { t } = useI18n();
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
  const isControlled = typeof expanded === 'boolean';
  const isExpanded = isControlled ? expanded : internalExpanded;

  if (!chain || !_hasContent(chain)) {
    return null;
  }

  const toggleExpanded = () => {
    const next = !isExpanded;
    if (!isControlled) {
      setInternalExpanded(next);
    }
    onExpandedChange?.(next);
  };

  return (
    <div
      className={cn(
        'rounded-md border border-outline-variant/60 bg-surface-low/40 text-xs',
        className,
      )}
    >
      <button
        type="button"
        onClick={toggleExpanded}
        className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-foreground/60 transition-colors hover:text-foreground"
        aria-expanded={isExpanded}
      >
        <span className="flex items-center gap-1.5 font-medium">
          {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {title || t('analysis_chain.section_label') || '证据化推理摘要'}
        </span>
        <span className="text-[10px] text-foreground/40">
          {isExpanded ? t('analysis_chain.collapse') : t('analysis_chain.expand')}
        </span>
      </button>
      {isExpanded && (
        <dl className="space-y-2 px-3 pb-3 pt-1 text-foreground/75">
          <Field label={t('analysis_chain.field_observation') || '观察'} value={chain.observation} />
          <Field label={t('analysis_chain.field_mechanism') || '机制'} value={chain.mechanism} />
          <FieldList
            label={t('analysis_chain.field_evidence') || '证据'}
            values={chain.evidence}
            projectId={projectId}
            selectedEvidenceId={selectedEvidenceId}
            onSelectEvidence={onSelectEvidence}
            navigateEvidenceAfterSelect={navigateEvidenceAfterSelect}
          />
          <Field label={t('analysis_chain.field_boundary') || '适用范围'} value={chain.boundary} />
          <FieldList
            label={t('analysis_chain.field_counter_evidence') || '反证'}
            values={chain.counter_evidence}
            projectId={projectId}
            selectedEvidenceId={selectedEvidenceId}
            onSelectEvidence={onSelectEvidence}
            navigateEvidenceAfterSelect={navigateEvidenceAfterSelect}
          />
          <Field
            label={t('analysis_chain.field_next_action') || '下一步'}
            value={chain.next_action}
          />
        </dl>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string }) {
  const trimmed = (value ?? '').trim();
  if (!trimmed) return null;
  return (
    <div>
      <dt className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-foreground/45">
        {label}
      </dt>
      <dd className="leading-relaxed">{trimmed}</dd>
    </div>
  );
}

function FieldList({
  label,
  values,
  projectId,
  selectedEvidenceId,
  onSelectEvidence,
  navigateEvidenceAfterSelect,
}: {
  label: string;
  values?: string[];
  projectId?: string | null;
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidence: EvidenceRefLike) => void;
  navigateEvidenceAfterSelect?: boolean;
}) {
  const filtered = (values ?? []).map((v) => v.trim()).filter(Boolean);
  if (filtered.length === 0) return null;
  return (
    <div>
      <dt className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-foreground/45">
        {label}
      </dt>
      <dd>
        <ul className="ml-4 list-disc space-y-0.5 leading-relaxed">
          {filtered.map((value, idx) => {
            const evidenceRef = parseAnalysisEvidenceRef(value, idx);
            return (
              <li key={idx}>
                <span>{evidenceRef ? formatAnalysisEvidenceSummary(evidenceRef, idx) : value}</span>
                {evidenceRef ? (
                  <span className="ml-2 inline-flex align-baseline">
                    <EvidencePill
                      evidence={evidenceRef}
                      projectId={projectId}
                      selected={
                        !!selectedEvidenceId &&
                        (evidenceRef.evidence_id === selectedEvidenceId || evidenceRef.chunk_id === selectedEvidenceId)
                      }
                      onActivate={onSelectEvidence}
                      navigateAfterActivate={navigateEvidenceAfterSelect}
                      labelOverride={`打开证据 ${idx + 1}`}
                      title={`打开证据 ${idx + 1}`}
                    />
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      </dd>
    </div>
  );
}

function parseAnalysisEvidenceRef(value: string, index: number): EvidenceRefLike | null {
  const chunkId = readKeyedValue(value, 'chunk_id');
  const materialId = readKeyedValue(value, 'material_id');
  if (!chunkId && !materialId) return null;
  const page = parsePage(readKeyedValue(value, 'page'));
  const source = readKeyedValue(value, 'source') ?? `证据 ${index + 1}`;
  return {
    evidence_id: chunkId ?? materialId,
    chunk_id: chunkId,
    material_id: materialId,
    page,
    source,
    text: value,
    source_type: 'project',
    source_kind: 'local',
  };
}

function formatAnalysisEvidenceSummary(evidence: EvidenceRefLike, index: number): string {
  const source = String(evidence.source ?? '').trim();
  const page = typeof evidence.page === 'number' && evidence.page > 0 ? ` · p.${evidence.page}` : '';
  return `[${index + 1}] ${source || `证据 ${index + 1}`}${page}`;
}

function readKeyedValue(value: string, key: string): string | null {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(?:^|[;\\s])${escaped}=([^;\\n]+)`).exec(value);
  const raw = match?.[1]?.trim() ?? '';
  return raw ? raw : null;
}

function parsePage(value: string | null): number | null {
  if (!value || !/^-?\d{1,5}$/.test(value.trim())) return null;
  const page = Number.parseInt(value.trim(), 10);
  return Number.isFinite(page) && page > 0 ? page : null;
}
