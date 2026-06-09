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
  navigateEvidenceAfterSelect?: boolean;

  /** Composer placeholder copy. */
  placeholder?: string;
  /** Controlled composer draft; omit to let ChatInput manage it locally. */
  inputValue?: string;
  /** Controlled composer change callback. */
  onInputValueChange?: (value: string) => void;
  /** Composer disabled state (e.g. while a request is in flight). */
  disabled?: boolean;
  /** True while a model request is active. */
  responding?: boolean;
  /** Cancel the active model request. */
  onStop?: () => void;
  /** Edit a sent user message by branching from that point. */
  onEditMessage?: (message: ChatMessageData) => void;
  /** Fork the visible conversation from a message. */
  onForkMessage?: (message: ChatMessageData) => void;
  /** Composer submit key behaviour. Inspector keeps `cmd-enter`; Dialog
   *  flips to `enter` for parity with its legacy composer. */
  submitKey?: 'enter' | 'cmd-enter';
  /** Footer hint shown under the composer. */
  composerHint?: string;
  /** Image attachment capability — opt-in. See ChatInput. */
  enableAttachments?: boolean;
  /** Composer textarea rows. */
  composerRows?: number;
  /** Current-request project reasoning-bias toggle rendered above composer. */
  projectReasoningBias?: {
    enabled: boolean;
    available: boolean;
    loading?: boolean;
    onChange: (enabled: boolean) => void;
  };

  /** Idle-state block shown when `messages` is empty. */
  emptyState?: ReactNode;
  /** Optional row above the transcript (e.g. selected-text context chip). */
  contextChips?: ReactNode;
  /** Optional controls rendered next to the composer, such as retrieval scope. */
  composerContext?: ReactNode;
  /** Optional row beneath the transcript and above the composer
   *  (e.g. typing indicator, error banner). */
  transcriptFooter?: ReactNode;
  /** Imperative handle for the composer (focus, etc.). */
  inputRef?: Ref<ChatInputHandle>;

  /** Outer wrapper className. */
  className?: string;
}

/**
 * Canonical chat surface.
 *
 * Composition of `MessageRenderer` + `ChatInput`. Pages decide their own
 * outer chrome (history drawer, context chips, attachment toggles) around
 * this component. Inspector and Dialog both use it for the unified
 * SmartRead surface.
 */
export function Conversation({
  messages,
  onSubmit,
  projectId,
  selectedEvidenceId,
  onSelectEvidence,
  navigateEvidenceAfterSelect = false,
  placeholder,
  inputValue,
  onInputValueChange,
  disabled,
  responding,
  onStop,
  onEditMessage,
  onForkMessage,
  submitKey,
  composerHint,
  enableAttachments,
  composerRows,
  projectReasoningBias,
  emptyState,
  contextChips,
  composerContext,
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
                navigateEvidenceAfterSelect={navigateEvidenceAfterSelect}
                onEditMessage={onEditMessage}
                onForkMessage={onForkMessage}
              />
            ))}
        {transcriptFooter}
      </div>

      <div className="shrink-0 border-t border-outline-variant/60 bg-surface-low p-2">
        {composerContext && <div className="mb-2">{composerContext}</div>}
        <ChatInput
          ref={inputRef}
          onSubmit={onSubmit}
          value={inputValue}
          onValueChange={onInputValueChange}
          placeholder={placeholder}
          disabled={disabled}
          responding={responding}
          onStop={onStop}
          submitKey={submitKey}
          rows={composerRows}
          enableAttachments={enableAttachments}
          hint={composerHint}
          projectReasoningBias={projectReasoningBias}
        />
      </div>
    </div>
  );
}
