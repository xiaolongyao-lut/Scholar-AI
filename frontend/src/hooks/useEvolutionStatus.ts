import { useCallback, useEffect, useState } from 'react';

import { getEvolutionStatus } from '../services/evolutionApi';
import type { EvolutionStatusPayload } from '../services/evolutionTypes';

export interface UseEvolutionStatusResult {
  status: EvolutionStatusPayload | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

// Read /evolution/status once on mount and expose a manual refresh.
// Kill-switch consumers should read `status.promotion_enabled`,
// `status.curator_enabled`, etc. directly; we keep this hook intentionally
// thin so the inbox page owns its loading/error UX and there is no hidden
// background polling.
export function useEvolutionStatus(): UseEvolutionStatusResult {
  const [status, setStatus] = useState<EvolutionStatusPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const next = await getEvolutionStatus();
      setStatus(next);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { status, isLoading, error, refresh };
}
