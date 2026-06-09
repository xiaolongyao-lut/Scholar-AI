import { Navigate } from 'react-router-dom';

/**
 * Compatibility route for the previous SmartRead page.
 *
 * All active AI conversation UX lives in `/dialog`, which uses the shared
 * Conversation surface with stop, edit, and fork controls. Keeping this
 * component as a redirect prevents stale duplicate chat controls from
 * regressing silently when an old deep link is opened.
 */
export function IntelligentChat() {
  return <Navigate to="/dialog" replace />;
}

export default IntelligentChat;
