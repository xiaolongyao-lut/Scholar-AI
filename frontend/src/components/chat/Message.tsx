/**
 * Compat alias — `Message` was the canonical chat renderer prior to the
 * fullstack deduplication plan (2026-05-24). The implementation now lives
 * in `MessageRenderer.tsx` (M-Slice 1a); this file keeps the original
 * `Message` / `ChatMessageData` / `ChatRole` exports stable so consumers
 * (ResearchWorkbenchInspector, DiscussionPanel, etc.) do not need to
 * update their imports during the migration.
 *
 * Once M-Slice 1b/4 (Conversation extraction) lands and consumers switch
 * to importing from `./MessageRenderer` directly, this alias can be
 * removed alongside `MessageBubble.tsx` in M-Slice 7.
 */
export { MessageRenderer as Message } from './MessageRenderer';
export type { ChatMessageData, ChatRole } from './MessageRenderer';
