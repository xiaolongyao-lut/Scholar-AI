import { useCallback, useEffect, useRef } from 'react';

/**
 * setTimeout whose IDs are tracked and cleared on component unmount.
 *
 * Why: many Settings panels call `setTimeout(() => setStatus('idle'), N)`
 * without cleanup. If the user leaves the page within N ms, React logs a
 * "setState on unmounted component" warning and the timer leaks. This hook
 * makes that the default-safe path.
 */
export function useTrackedTimeout(): (cb: () => void, ms: number) => number {
  const timersRef = useRef<number[]>([]);

  useEffect(
    () => () => {
      timersRef.current.forEach((id) => window.clearTimeout(id));
      timersRef.current = [];
    },
    []
  );

  return useCallback((cb: () => void, ms: number): number => {
    const id = window.setTimeout(cb, ms);
    timersRef.current.push(id);
    return id;
  }, []);
}
