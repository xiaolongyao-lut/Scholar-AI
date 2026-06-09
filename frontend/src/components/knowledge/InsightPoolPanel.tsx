import EvolutionInbox from '@/pages/EvolutionInbox';

/**
 * Render the reviewable insight implementation under the product name 洞察池.
 *
 * Why:
 * Evolution keeps the candidate lifecycle and promotion rules, while this panel
 * exposes it as a review pool inside the unified knowledge workbench.
 */
export function InsightPoolPanel() {
  return <EvolutionInbox embedded />;
}
