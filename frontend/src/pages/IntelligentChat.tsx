import axios from 'axios';
import { useState, useRef, useEffect } from 'react';
import { MessageCircle, RefreshCw, Send, AlertCircle, History, X } from 'lucide-react';
import { TierSelector } from '@/components/chat/TierSelector';
import { MessageBubble } from '@/components/chat/MessageBubble';
import {
  sendIntelligentChatMessage,
  listChatSessions,
  resumeChatSession,
  ContextTier,
  IntelligentChatResponse,
  ChatSessionSummary,
  ChatResumeMessage,
} from '@/services/intelligentChatApi';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  tierUsed?: ContextTier;
  contextMetadata?: IntelligentChatResponse['context_metadata'];
  evidenceRefs?: IntelligentChatResponse['evidence_refs'];
  actualSamplingParams?: IntelligentChatResponse['actual_sampling_params'];
  timestamp: Date;
  insufficientContext?: boolean;
}

type ChatState = 'ready' | 'responding' | 'error' | 'unavailable';

type HistoryState = 'idle' | 'loading' | 'error';

function getChatErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error) && error.response) {
    const detail = error.response.data?.detail ?? error.response.data?.error?.message;
    if (typeof detail === 'string') {
      return detail;
    }
    if (detail && typeof detail === 'object') {
      return JSON.stringify(detail);
    }
    return `Request failed (${error.response.status})`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return 'Failed to send message. Please try again.';
}

function isUnavailableError(error: unknown): boolean {
  if (!axios.isAxiosError(error) || !error.response) {
    return false;
  }

  if (error.response.status !== 400) {
    return false;
  }

  const detail = error.response.data?.detail;
  const message = typeof detail === 'string' ? detail : error.response.data?.error?.message;
  return typeof message === 'string' && message.toLowerCase().includes('no literature source paths configured');
}

function parseChatTimestamp(value: string): Date {
  if (!value.trim()) {
    return new Date();
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function toChatMessage(message: ChatResumeMessage): ChatMessage {
  if (message.role !== 'user' && message.role !== 'assistant') {
    throw new Error('Unsupported chat message role');
  }
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    tierUsed: message.tier_used ?? undefined,
    contextMetadata: message.context_metadata ?? undefined,
    evidenceRefs: undefined,
    timestamp: parseChatTimestamp(message.timestamp),
    insufficientContext: message.role === 'assistant' && !message.context_metadata,
  };
}

export function IntelligentChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [selectedTier, setSelectedTier] = useState<ContextTier>('balanced');
  const [chatState, setChatState] = useState<ChatState>('ready');
  const [historyState, setHistoryState] = useState<HistoryState>('idle');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isUnavailable, setIsUnavailable] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const refreshSessions = async () => {
    setHistoryState('loading');
    try {
      const nextSessions = await listChatSessions();
      setSessions(nextSessions);
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleNewSession = () => {
    setMessages([]);
    setSessionId(undefined);
    setErrorMessage(null);
    setIsUnavailable(false);
    setChatState('ready');
  };

  const handleOpenHistory = async () => {
    setHistoryOpen(true);
    await refreshSessions();
  };

  const handleResumeSession = async (nextSessionId: string) => {
    const normalizedSessionId = nextSessionId.trim();
    if (!normalizedSessionId || chatState === 'responding') {
      return;
    }

    setHistoryState('loading');
    setErrorMessage(null);
    try {
      const response = await resumeChatSession({ session_id: normalizedSessionId, limit: 100 });
      setSessionId(response.session_id);
      setMessages(response.messages.map(toChatMessage));
      setIsUnavailable(false);
      setChatState('ready');
      setHistoryOpen(false);
      setHistoryState('idle');
    } catch (error) {
      setHistoryState('error');
      setErrorMessage(getChatErrorMessage(error));
    }
  };

  const handleSendMessage = async () => {
    const query = inputValue.trim();
    if (!query || chatState === 'responding') {
      return;
    }

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setChatState('responding');
    setErrorMessage(null);

    try {
      const response = await sendIntelligentChatMessage({
        query,
        session_id: sessionId,
        tier: selectedTier,
      });

      if (!sessionId) {
        setSessionId(response.session_id);
      }

      setIsUnavailable(false);
      const hasInsufficientContext = response.context_chunks_used === 0;

      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.response,
        tierUsed: response.tier_used,
        contextMetadata: response.context_metadata,
        evidenceRefs: response.evidence_refs,
        actualSamplingParams: response.actual_sampling_params,
        timestamp: new Date(),
        insufficientContext: hasInsufficientContext,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setChatState('ready');
    } catch (error) {
      console.error('Chat error:', error);
      const errorMsg = getChatErrorMessage(error);
      
      if (isUnavailableError(error)) {
        setIsUnavailable(true);
        setChatState('unavailable');
      } else {
        setIsUnavailable(false);
        setErrorMessage(errorMsg);
        setChatState('error');
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const isInputDisabled = chatState === 'responding';

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-gray-50">
        <div className="flex items-center gap-3">
          <MessageCircle className="w-6 h-6 text-blue-600" />
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Intelligent Chat</h1>
            {sessionId && (
              <p className="text-sm text-gray-500">Session: {sessionId}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleOpenHistory}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <History className="w-4 h-4" />
            History
          </button>
          <button
            type="button"
            onClick={handleNewSession}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            New Session
          </button>
        </div>
      </div>

      {historyOpen && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={() => setHistoryOpen(false)}>
          <aside
            className="h-full w-full max-w-md bg-white shadow-xl border-l border-gray-200 flex flex-col"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Chat History</h2>
                <p className="text-xs text-gray-500">Resume a previous grounded conversation</p>
              </div>
              <button
                type="button"
                onClick={() => setHistoryOpen(false)}
                className="p-2 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
                aria-label="Close history"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-5 py-3 border-b border-gray-100">
              <button
                type="button"
                onClick={refreshSessions}
                disabled={historyState === 'loading'}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
              >
                <RefreshCw className={`w-4 h-4 ${historyState === 'loading' ? 'animate-spin' : ''}`} />
                Refresh History
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {historyState === 'loading' && sessions.length === 0 ? (
                <div className="text-sm text-gray-500 text-center py-8">Loading sessions...</div>
              ) : sessions.length === 0 ? (
                <div className="text-sm text-gray-500 text-center py-8">No saved sessions yet.</div>
              ) : (
                sessions.map((item) => (
                  <button
                    key={item.session_id}
                    type="button"
                    onClick={() => handleResumeSession(item.session_id)}
                    disabled={historyState === 'loading' || chatState === 'responding'}
                    className="w-full text-left p-4 border border-gray-200 rounded-lg hover:border-blue-300 hover:bg-blue-50 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                  >
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <span className="font-mono text-xs text-gray-600 truncate">{item.session_id}</span>
                      <span className="text-xs text-gray-500 whitespace-nowrap">{item.total_turns} turns</span>
                    </div>
                    <p className="text-sm text-gray-900 line-clamp-2">{item.preview || 'Untitled session'}</p>
                    {item.updated_at && (
                      <p className="mt-2 text-xs text-gray-500">
                        Updated {parseChatTimestamp(item.updated_at).toLocaleString()}
                      </p>
                    )}
                  </button>
                ))
              )}
            </div>
          </aside>
        </div>
      )}

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {/* Unavailable State Banner */}
        {isUnavailable && (
          <div className="mb-4 p-4 bg-yellow-50 border-l-4 border-yellow-400 rounded-lg">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="text-sm font-semibold text-yellow-800 mb-1">
                  Chat Service Unavailable
                </h3>
                <p className="text-sm text-yellow-700 mb-2">
                  No literature sources are currently configured in the knowledge base.
                </p>
                <p className="text-xs text-yellow-600">
                  To use Intelligent Chat, please add literature sources in the <strong>Knowledge Base</strong> section first.
                </p>
              </div>
            </div>
          </div>
        )}

        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <MessageCircle className="w-16 h-16 text-gray-300 mb-4" />
            <h2 className="text-xl font-semibold text-gray-700 mb-2">
              Start a conversation
            </h2>
            <p className="text-gray-500 max-w-md">
              Ask questions about your literature collection. The AI will retrieve relevant
              context and provide grounded answers.
            </p>
          </div>
        ) : (
          messages.map((message) => (
            <MessageBubble
              key={message.id}
              role={message.role}
              content={message.content}
              tierUsed={message.tierUsed}
              contextMetadata={message.contextMetadata}
              evidenceRefs={message.evidenceRefs}
              actualSamplingParams={message.actualSamplingParams}
              timestamp={message.timestamp}
              insufficientContext={message.insufficientContext}
            />
          ))
        )}

        {chatState === 'responding' && (
          <div className="flex justify-start">
            <div className="bg-gray-100 border border-gray-200 rounded-lg px-4 py-3">
              <div className="flex items-center gap-2 text-gray-600">
                <div className="flex gap-1">
                  <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                  <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                  <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
                </div>
                <span className="text-sm">Thinking...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Error Banner */}
      {errorMessage && (
        <div className="px-6 py-3 bg-red-50 border-t border-red-200">
          <div className="flex items-center justify-between">
            <p className="text-sm text-red-800">{errorMessage}</p>
            <button
              type="button"
              onClick={() => setErrorMessage(null)}
              className="text-sm text-red-600 hover:text-red-800 font-medium"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Input Area */}
      <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
        <div className="mb-3">
          <TierSelector
            selectedTier={selectedTier}
            onTierChange={setSelectedTier}
            disabled={isInputDisabled}
          />
        </div>

        <div className="flex gap-3">
          <textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isInputDisabled}
            placeholder="Ask a question about your literature..."
            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
            rows={3}
          />
          <button
            type="button"
            onClick={handleSendMessage}
            disabled={isInputDisabled || !inputValue.trim()}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <Send className="w-5 h-5" />
            <span className="font-medium">Send</span>
          </button>
        </div>

        <p className="mt-2 text-xs text-gray-500">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
