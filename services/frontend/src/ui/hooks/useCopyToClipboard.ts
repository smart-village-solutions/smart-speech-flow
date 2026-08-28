import { useCallback, useEffect, useRef, useState } from 'react';

export type CopyState = 'idle' | 'copied' | 'failed';

/** How long the outcome shows before the label returns to its prompt. */
const RESET_MS = 2000;

/**
 * The clipboard is a browser API with one implementation and nothing to swap,
 * so it is a hook rather than a port. Failure is a state, not an exception: it
 * happens on every page served over plain HTTP, where `navigator.clipboard` is
 * absent entirely, and the link stays on screen as selectable text either way.
 */
export function useCopyToClipboard() {
  const [state, setState] = useState<CopyState>('idle');
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
    } catch {
      setState('failed');
    }

    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState('idle'), RESET_MS);
  }, []);

  return { state, copy };
}
