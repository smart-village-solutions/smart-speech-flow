import { useEffect } from 'react';

/** Marks what an outside tap must not treat as outside. */
const KEEP_OPEN_ATTRIBUTE = 'data-dismiss-keep';

/**
 * Closes a transient surface on a tap that lands away from it. Touch has no
 * Escape key, so without this the conversation composer is a trap — the mic is
 * disabled while it is open and send is disabled until something is typed — and
 * the admin user menu has no way to close at all. Mark the surface and anything
 * that must not count as "outside" with `data-dismiss-keep`.
 *
 * Lives in `ui/` rather than beside the composer because `ui/` may not import
 * from `features/`: dependencies point downward only.
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
