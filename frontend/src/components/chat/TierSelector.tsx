import {
  SMART_READ_TIER_CONFIG,
  SMART_READ_TIERS,
  type SmartReadCostTier,
} from '@/services/smartReadTiers';
import { clsx } from 'clsx';

interface TierSelectorProps {
  selectedTier: SmartReadCostTier;
  onTierChange: (tier: SmartReadCostTier) => void;
  disabled?: boolean;
  compact?: boolean;
  label?: string;
}

export function TierSelector({
  selectedTier,
  onTierChange,
  disabled,
  compact = false,
  label = '成本模式',
}: TierSelectorProps) {
  return (
    <div className={clsx('flex min-w-0 flex-col gap-1.5', compact && 'gap-1')}>
      <label className={clsx('font-medium text-foreground/65', compact ? 'text-[11px]' : 'text-xs')}>
        {label}
      </label>
      <div
        className={clsx(
          'inline-flex w-fit max-w-full flex-wrap rounded-lg border border-outline-variant/70 bg-surface-lowest p-1',
          compact && 'rounded-md p-0.5',
        )}
        role="group"
        aria-label={label}
      >
        {SMART_READ_TIERS.map((tier) => (
          <button
            key={tier}
            type="button"
            onClick={() => onTierChange(tier)}
            disabled={disabled}
            title={SMART_READ_TIER_CONFIG[tier].tooltip}
            className={clsx(
              'font-label font-medium transition-all focus:outline-none focus:ring-2 focus:ring-primary/30',
              compact ? 'rounded px-2 py-1 text-[11px]' : 'rounded-md px-3 py-1.5 text-xs',
              selectedTier === tier
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-foreground/60 hover:bg-surface-high hover:text-foreground',
              disabled && 'opacity-50 cursor-not-allowed'
            )}
          >
            {compact ? SMART_READ_TIER_CONFIG[tier].shortLabel : SMART_READ_TIER_CONFIG[tier].label}
          </button>
        ))}
      </div>
    </div>
  );
}
