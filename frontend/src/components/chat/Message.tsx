/**
 * Compatibility alias that keeps the legacy `Message` export stable while
 * consumers migrate to `MessageRenderer.tsx` directly.
 */
export { MessageRenderer as Message } from './MessageRenderer';
export type { ChatMessageData, ChatRole } from './MessageRenderer';
