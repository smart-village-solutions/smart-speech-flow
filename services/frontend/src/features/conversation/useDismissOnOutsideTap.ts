import { useEffect } from 'react';

/** Marks what an outside tap must not treat as outside. */
const KEEP_OPEN_ATTRIBUTE = 'data-composer-keep';

/**
 * Closes the text composer on a tap that lands away from it. Without this the
 * keyboard is a trap: the mic is disabled while the composer is open, the send
 * button is disabled until something is typed, and touch has no Escape key.
 */
export function useDismissOnOutsideTap(active: boolean, onDismiss: () => void) {
  useEffect(() => {
    if (!active) {
      return;
    }

    const handleTap = (event: Event) => {
      const { target } = event;
      if (target instanceof Element && target.closest(`[${KEEP_OPEN_ATTRIBUTE}]`) !== null) {
        return;
      }
      onDismiss();
    };

    document.addEventListener('pointerdown', handleTap);
    return () => document.removeEventListener('pointerdown', handleTap);
  }, [active, onDismiss]);
}
