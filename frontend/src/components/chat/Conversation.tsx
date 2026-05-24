import { type ReactNode, type Ref } from 'react';
import { MessageRenderer, type ChatMessageData } from './MessageRenderer';
import { ChatInput, type ChatInputHandle, type ChatInputSubmitPayload } from './ChatInput';
import type { EvidenceRefLike } from '@/components/evidence/EvidencePill';
import { cn } from '@/lib/utils';

interface ConversationProps {
  /** Messages rendered top-to-bottom. */
  messages: ChatMessageData[];
  /** Called when the user submits via the composer. */
  onSubmit(payload: ChatInputSubmitPayload): void;
  /** Forwarded to EvidencePill for locator upgrade. */
  projectId?: string | null;
  /** Selection bus glue — focused evidence id (chunk_id / evidence_id). */
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidence: EvidenceRefLike) => void;

  /** Composer placeholder copy. */
  placeholder?: string;
  /** Composer disabled state (e.g. while a request is in flight). */
  disabled?: boolean;
  /** Composer submit key behaviour. Inspector keeps `cmd-enter`; Dialog
   *  flips to `enter` for parity with its legacy composer. */
  submitKey?: 'enter' | 'cmd-enter';
  /** Footer hint shown under the composer. */
  composerHint?: string;
  /** Image attachment capability — opt-in. See ChatInput. */
  enableAttachments?: boolean;
  /** Composer textarea rows. */
  composerRows?: number;

  /** Idle-state block shown when `messages` is empty. */
  emptyState?: ReactNode;
  /** Optional row above the transcript (e.g. selected-text context chip). */
  contextChips?: ReactNode;
  /** Optional row beneath the transcript and above the composer
   *  (e.g. typing indicator, error banner). */
  transcriptFooter?: ReactNode;
  /** Imperative handle for the composer (focus, etc.). */
  inputRef?: Ref<ChatInputHandle>;

  /** Outer wrapper className. */
  className?: string;
}

/**
 * Canonical chat surface (M-Slice 1b).
 *
 * Composition of `MessageRenderer` + `ChatInput`. Pages decide their own
 * outer chrome (mode toggle, history drawer, attachment-mode toggles)
 * around this component. Inspector smart-read uses the bare composition;
 * Dialog wraps it with its mode toolbar + inspiration drawer + history
 * sheet in M-Slice 1b.d.
 */
export function Conversation({
  messages,
  onSubmit,
  projectId,
  selectedEvidenceId,
  onSelectEvidence,
  placeholder,
  disabled,
  submitKey,
  composerHint,
  enableAttachments,
  composerRows,
  emptyState,
  contextChips,
  transcriptFooter,
  inputRef,
  className,
}: ConversationProps) {
  return (
    <div className={cn('flex h-full min-h-0 flex-col', className)}>
      {contextChips && (
        <div className="shrink-0 border-b border-outline-variant/40 px-3 py-2">{contextChips}</div>
      )}

      <div className="min-h-0 flex-1 space-y-3 overflow-auto px-3 py-3">
        {messages.length === 0 && emptyState
          ? emptyState
          : messages.map((m) => (
              <MessageRenderer
                key={m.id}
                message={m}
                projectId={projectId}
                selectedEvidenceId={selectedEvidenceId}
                onSelectEvidence={onSelectEvidence}
              />
            ))}
        {transcriptFooter}
      </div>

      <div className="shrink-0 border-t border-outline-variant/60 bg-surface-low p-2">
        <ChatInput
          ref={inputRef}
          onSubmit={onSubmit}
          placeholder={placeholder}
          disabled={disabled}
          submitKey={submitKey}
          rows={composerRows}
          enableAttachments={enableAttachments}
          hint={composerHint}
        />
      </div>
    </div>
  );
}
