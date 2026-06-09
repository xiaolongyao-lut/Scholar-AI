import { useCallback, useEffect, useState } from 'react';
import {
  loadSmartReadCostTier,
  saveSmartReadCostTier,
  subscribeSmartReadCostTier,
  type SmartReadCostTier,
} from '@/services/smartReadTiers';

export function useSmartReadCostTier(
  fallback: SmartReadCostTier = 'medium',
): readonly [SmartReadCostTier, (tier: SmartReadCostTier) => void] {
  const [tier, setTierState] = useState<SmartReadCostTier>(() => loadSmartReadCostTier(fallback));

  useEffect(() => subscribeSmartReadCostTier(setTierState), []);

  const setTier = useCallback((nextTier: SmartReadCostTier) => {
    setTierState(nextTier);
    saveSmartReadCostTier(nextTier);
  }, []);

  return [tier, setTier] as const;
}
