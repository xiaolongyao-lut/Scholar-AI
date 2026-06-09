import { Check, Loader2, Square } from 'lucide-react';
import { Modal, ModalBody, ModalFooter, ModalHeader } from '@/components/ui/Modal';
import type { ProjectReasoningBiasOptimizeResponse } from '@/types/resources';

interface ReasoningBiasOptimizerDialogProps {
  open: boolean;
  result: ProjectReasoningBiasOptimizeResponse | null;
  loading: boolean;
  error: string;
  onClose: () => void;
  onAdopt: (optimizedBias: string) => void;
  onStop?: () => void;
}

const fieldLabels: Array<keyof ProjectReasoningBiasOptimizeResponse['field_suggestions']> = [
  'observation',
  'mechanism',
  'evidence',
  'boundary',
  'counter_evidence',
  'next_action',
];

const labelText: Record<keyof ProjectReasoningBiasOptimizeResponse['field_suggestions'], string> = {
  observation: '观察',
  mechanism: '机制',
  evidence: '证据',
  boundary: '边界',
  counter_evidence: '反证',
  next_action: '下一步',
};

export function ReasoningBiasOptimizerDialog({
  open,
  result,
  loading,
  error,
  onClose,
  onAdopt,
  onStop,
}: ReasoningBiasOptimizerDialogProps) {
  return (
    <Modal open={open} onClose={onClose} size="xl" labelledBy="bias-optimizer-title">
      <ModalHeader className="pr-12">
        <h2 id="bias-optimizer-title" className="font-headline text-base font-semibold text-foreground">
          AI 优化项目思维偏置
        </h2>
        <p className="mt-1 text-xs leading-5 text-foreground/55">
          优化结果只作为建议显示，点击采纳后才会写入输入框。
        </p>
      </ModalHeader>
      <ModalBody className="max-h-[68vh] space-y-4">
        {loading && (
          <div className="flex min-h-32 flex-col items-center justify-center gap-3 text-sm text-foreground/60">
            <div className="inline-flex items-center gap-2">
              <Loader2 size={16} className="animate-spin text-primary" />
              正在生成建议
            </div>
            {onStop && (
              <button
                type="button"
                onClick={onStop}
                className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-outline-variant/70 bg-surface-low px-3 py-1.5 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
              >
                <Square size={12} />
                停止生成
              </button>
            )}
          </div>
        )}
        {!loading && error && (
          <div className="rounded-md border border-red-300/70 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-500/10 dark:text-red-300">
            {error}
          </div>
        )}
        {!loading && result && (
          <>
            <section>
              <h3 className="text-xs font-semibold text-foreground/75">优化版</h3>
              <p className="mt-2 whitespace-pre-wrap rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm leading-6 text-foreground">
                {result.optimized_bias}
              </p>
            </section>

            <section>
              <h3 className="text-xs font-semibold text-foreground/75">思考模式建议</h3>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {fieldLabels.map((field) => (
                  <div key={field} className="rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2">
                    <div className="text-[11px] font-medium text-foreground/50">{labelText[field]}</div>
                    <p className="mt-1 text-xs leading-5 text-foreground/75">
                      {result.field_suggestions[field] || '—'}
                    </p>
                  </div>
                ))}
              </div>
            </section>

            {result.safety_notes.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold text-foreground/75">边界说明</h3>
                <ul className="mt-2 space-y-1 text-xs leading-5 text-foreground/65">
                  {result.safety_notes.map((note) => (
                    <li key={note} className="flex gap-2">
                      <Check size={12} className="mt-1 shrink-0 text-emerald-600 dark:text-emerald-300" />
                      <span>{note}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </ModalBody>
      <ModalFooter>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-outline-variant/60 px-3 py-1.5 text-xs font-medium text-foreground/70 hover:bg-surface-low"
        >
          关闭
        </button>
        <button
          type="button"
          disabled={!result || loading}
          onClick={() => {
            if (result) onAdopt(result.optimized_bias);
          }}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          采纳优化版
        </button>
      </ModalFooter>
    </Modal>
  );
}
