import { useEffect, useRef, type RefObject } from 'react';

/**
 * Mirrors a rendered value into a ref after each commit, for callbacks that run
 * outside render and would otherwise close over a stale one.
 */
export function useLatestRef<T>(value: T): RefObject<T> {
  const ref = useRef(value);

  useEffect(() => {
    ref.current = value;
  });

  return ref;
}
