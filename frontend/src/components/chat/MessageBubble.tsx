import { useState } from 'react';
import { ChevronDown, ChevronRight, AlertTriangle } from 'lucide-react';
import { ContextMetadata, ContextTier, EvidenceReference } from '@/services/intelligentChatApi';
import { Tooltip } from '@/components/ui/Tooltip';
import { getEvidenceReferenceWikiUrl } from '@/lib/evidenceReferences';
import { clsx } from 'clsx';

interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  tierUsed?: ContextTier;
  contextMetadata?: ContextMetadata;
  evidenceRefs?: EvidenceReference[];
  timestamp?: Date;
  insufficientContext?: boolean;
  actualSamplingParams?: {
    temperature: number;
    top_p: number;
    top_k: number;
    max_tokens: number;
  };
}

export function MessageBubble({
  role,
  content,
  tierUsed,
  contextMetadata,
  evidenceRefs,
  timestamp,
  insufficientContext,
  actualSamplingParams,
}: MessageBubbleProps) {
  const [contextExpanded, setContextExpanded] = useState(false);

  const isUser = role === 'user';

  const renderContentWithCitations = (text: string) => {
    if (isUser) return text;

    // 正则匹配 [chunk-xxx] 或 [id]
    const parts = text.split(/(\[chunk-[a-zA-Z0-9_-]+\]|\[[a-zA-Z0-9_-]+\])/g);
    return parts.map((part, i) => {
      const match = part.match(/^\[(chunk-)?([a-zA-Z0-9_-]+)\]$/);
      if (match) {
        const id = match[0];
        return (
          <button
            key={i}
            onClick={() => {
              // 触发全局定位事件，Dozer 将在这个项目的其它部分订阅这个事件
              window.dispatchEvent(new CustomEvent('cite-locate', { detail: { id } }));
            }}
            className="mx-0.5 px-1 rounded bg-blue-100 text-blue-700 font-mono text-[10px] hover:bg-blue-200 transition-colors"
          >
            {id}
          </button>
        );
      }
      return part;
    });
  };

  return (
    <div className={clsx('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={clsx(
          'max-w-[80%] rounded-lg px-4 py-3',
          isUser
            ? 'bg-blue-500 text-white'
            : 'bg-gray-100 text-gray-900 border border-gray-200'
        )}
      >
        {/* Insufficient Context Warning Badge */}
        {!isUser && insufficientContext && (
          <div className="mb-2 flex items-center gap-2 px-3 py-2 bg-yellow-50 border border-yellow-200 rounded text-yellow-800 text-xs">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span className="font-medium">
              Limited context: No relevant sources found for this query
            </span>
          </div>
        )}

        <div className="whitespace-pre-wrap break-words">
          {renderContentWithCitations(content)}
        </div>

        {!isUser && contextMetadata && contextMetadata.chunks.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <button
              type="button"
              onClick={() => setContextExpanded(!contextExpanded)}
              className="flex items-center gap-1 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              {contextExpanded ? (
                <ChevronDown className="w-4 h-4" />
              ) : (
                <ChevronRight className="w-4 h-4" />
              )}
              <span>
                Context used ({contextMetadata.chunks.length} chunk
                {contextMetadata.chunks.length !== 1 ? 's' : ''} from{' '}
                {new Set(contextMetadata.chunks.map((c) => c.source)).size} paper
                {new Set(contextMetadata.chunks.map((c) => c.source)).size !== 1 ? 's' : ''})
              </span>
            </button>

            {contextExpanded && (
              <div className="mt-2 space-y-2">
                {contextMetadata.chunks.map((chunk) => (
                  <div
                    key={chunk.index}
                    className="bg-white rounded border border-gray-200 p-3 text-xs"
                  >
                    <div className="font-semibold text-gray-900 mb-1">
                      [{chunk.index}] {chunk.source}
                    </div>
                    <div className="text-gray-600 line-clamp-3">{chunk.content}</div>
                    {chunk.relevance_score !== undefined && (
                      <div className="mt-1 text-gray-500">
                        Relevance: {chunk.relevance_score.toFixed(3)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {!isUser && evidenceRefs && evidenceRefs.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Evidence References
            </div>
            <div className="space-y-2">
              {evidenceRefs.slice(0, 5).map((ref, index) => {
                const wikiUrl = getEvidenceReferenceWikiUrl(ref);

                return (
                  <div
                    key={`${ref.chunk_id}-${index}`}
                    className="rounded border border-blue-100 bg-blue-50/60 p-2 text-xs text-gray-700"
                  >
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <span className="font-mono text-blue-700">[{ref.chunk_id}]</span>
                      <span className="font-medium text-gray-800">{ref.source}</span>
                      {typeof ref.score === 'number' && (
                        <span className="text-gray-500">score {ref.score.toFixed(3)}</span>
                      )}
                      {wikiUrl && (
                        <a
                          href={wikiUrl}
                          className="rounded border border-blue-200 bg-white/70 px-1.5 py-0.5 font-medium text-blue-700 transition-colors hover:bg-blue-100"
                        >
                          Wiki preview
                        </a>
                      )}
                    </div>
                    <div className="line-clamp-2 text-gray-600">{ref.quote || ref.text}</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {!isUser && tierUsed && (
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-gray-500">
            <span className="inline-block px-2 py-0.5 rounded bg-gray-200 text-gray-700">
              {tierUsed.charAt(0).toUpperCase() + tierUsed.slice(1)}
            </span>
            {actualSamplingParams && (
              <Tooltip content={`Temp: ${actualSamplingParams.temperature}, TopP: ${actualSamplingParams.top_p}, TopK: ${actualSamplingParams.top_k}`}>
                <span className="inline-block px-2 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-100 cursor-help">
                  Sampling Active
                </span>
              </Tooltip>
            )}
          </div>
        )}

        {timestamp && (
          <div className="mt-1 text-xs opacity-60">
            {timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
        )}
      </div>
    </div>
  );
}
