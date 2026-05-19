/**
 * Pure helpers for SessionDrawer. Kept separate so they can be unit-tested
 * without a React renderer; the existing lightweight `node:test` coverage for
 * these helpers remains useful even after the frontend gained Vitest-based
 * component tests.
 *
 * Plan: docs/superpowers/plans/2026-04-20-conversation-persistence-mvp.md §S-4
 */

import type {
  SessionSummary,
  TimelineEvent,
} from "../../types/runtime";

export interface WorkbenchMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  sources?: { title: string; page: string; material_id?: string; chunk_id?: string; page_number?: number }[];
  error?: boolean;
  usage?: Record<string, number>;
  model?: string;
}

export function mapTimelineToMessages(timeline: TimelineEvent[]): WorkbenchMessage[] {
  const messages: WorkbenchMessage[] = [];
  for (const event of timeline) {
    if (event.event_kind === 'user' || event.event_kind === 'assistant') {
      const payload = event.payload || {};
      const content =
        (typeof payload.text === "string" && payload.text) ||
        (typeof payload.content === "string" && payload.content) ||
        "";
      
      const parsedTime = Date.parse(event.timestamp);
      const id = Number.isFinite(parsedTime) ? parsedTime : Math.random();

      messages.push({
        id,
        role: event.event_kind,
        content,
        usage: payload.usage as Record<string, number> | undefined,
        sources: Array.isArray(payload.sources) ? payload.sources as any : undefined,
        model: typeof payload.model === 'string' ? payload.model : undefined,
      });
    }
  }
  return messages;
}

/** Cap drawer list to N items sorted by updated_at (fallback created_at) desc. */
export function sortAndLimitSessions(
  sessions: SessionSummary[],
  limit: number = 10,
): SessionSummary[] {
  const getTimestamp = (s: SessionSummary): number => {
    const candidate =
      (typeof s.metadata?.updated_at === "string"
        ? (s.metadata.updated_at as string)
        : null) ?? s.created_at;
    const parsed = Date.parse(candidate);
    return Number.isFinite(parsed) ? parsed : 0;
  };

  return [...sessions]
    .sort((a, b) => getTimestamp(b) - getTimestamp(a))
    .slice(0, Math.max(0, limit));
}

/** First 8 chars of session_id, for compact display. */
export function shortSessionId(sessionId: string): string {
  if (!sessionId) return "";
  return sessionId.slice(0, 8);
}

/**
 * Extract a short preview from the first user turn in metadata or timeline.
 * Falls back to session title or "(empty session)".
 */
export function sessionPreviewText(
  session: SessionSummary,
  maxChars: number = 40,
): string {
  const title =
    typeof session.metadata?.title === "string"
      ? (session.metadata.title as string)
      : null;
  const firstPrompt =
    typeof session.metadata?.first_user_prompt === "string"
      ? (session.metadata.first_user_prompt as string)
      : null;
  const raw = title ?? firstPrompt ?? "";
  const trimmed = raw.trim();
  if (!trimmed) return "(empty session)";
  if (trimmed.length <= maxChars) return trimmed;
  return trimmed.slice(0, Math.max(0, maxChars - 1)) + "…";
}

/** True when this session was forked from another (shows fork badge). */
export function isForkedSession(session: SessionSummary): boolean {
  const parent = session.metadata?.parent_session_id;
  return typeof parent === "string" && parent.length > 0;
}

/** Four UI bucket kinds. Unknown kinds fold into `other`. */
export type TimelineDisplayKind =
  | "user"
  | "assistant"
  | "tool_call"
  | "tool_result"
  | "checkpoint"
  | "other";

/** Map backend event_kind to display bucket. */
export function classifyTimelineEvent(
  event: TimelineEvent,
): TimelineDisplayKind {
  switch (event.event_kind) {
    case "user":
    case "assistant":
    case "tool_call":
    case "tool_result":
    case "checkpoint":
      return event.event_kind;
    default:
      return "other";
  }
}

/**
 * Next cursor resolution — prefer explicit next_cursor from backend, fall back
 * to last event_id in the page (safe for cursor-after pagination).
 */
export function resolveNextCursor(
  items: TimelineEvent[],
  nextCursor?: string | null,
): string | null {
  if (typeof nextCursor === "string" && nextCursor.length > 0) return nextCursor;
  if (items.length === 0) return null;
  return items[items.length - 1].event_id;
}

/** Human-friendly relative timestamp (e.g. "3m", "2h", "4d", "2026-04-20"). */
export function formatRelativeTimestamp(
  iso: string,
  now: number = Date.now(),
): string {
  const parsed = Date.parse(iso);
  if (!Number.isFinite(parsed)) return iso;
  const diffMs = now - parsed;
  if (diffMs < 0) return iso;
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  const day = Math.floor(hr / 24);
  if (day < 14) return `${day}d`;
  // Fall back to date-only for older entries.
  return iso.slice(0, 10);
}
