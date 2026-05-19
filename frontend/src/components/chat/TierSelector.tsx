import { ContextTier } from '@/services/intelligentChatApi';
import { clsx } from 'clsx';

interface TierSelectorProps {
  selectedTier: ContextTier;
  onTierChange: (tier: ContextTier) => void;
  disabled?: boolean;
}

const TIER_CONFIG: Record<ContextTier, { label: string; tooltip: string }> = {
  fast: {
    label: 'Fast',
    tooltip: 'Top 5 papers, ~2K tokens. Quick response but less context.',
  },
  balanced: {
    label: 'Balanced',
    tooltip: 'Top 10 papers, ~6K tokens. Good tradeoff for most questions.',
  },
  thorough: {
    label: 'Thorough',
    tooltip: 'Top 15 papers, ~12K tokens. Comprehensive but slower and higher cost.',
  },
};

export function TierSelector({ selectedTier, onTierChange, disabled }: TierSelectorProps) {
  const tiers: ContextTier[] = ['fast', 'balanced', 'thorough'];

  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-medium text-gray-700">Context Tier:</label>
      <div className="inline-flex rounded-lg border border-gray-200 bg-white p-1" role="group">
        {tiers.map((tier) => (
          <button
            key={tier}
            type="button"
            onClick={() => onTierChange(tier)}
            disabled={disabled}
            title={TIER_CONFIG[tier].tooltip}
            className={clsx(
              'px-4 py-2 text-sm font-medium rounded-md transition-all',
              'focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-blue-500',
              selectedTier === tier
                ? 'bg-blue-600 text-white shadow-sm'
                : 'text-gray-700 hover:bg-gray-50',
              disabled && 'opacity-50 cursor-not-allowed'
            )}
          >
            {TIER_CONFIG[tier].label}
          </button>
        ))}
      </div>
    </div>
  );
}
