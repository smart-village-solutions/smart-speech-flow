import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import type { ResolvedFeedbackForm } from './resolveFeedbackForm';
import { useFeedbackForm } from './useFeedbackForm';

/** As long as the first paint waits for installation content: then bundled is the answer. */
const FORM_WAIT_MS = 1_000;

/**
 * The form an open sheet shows, frozen the moment it is known: once content has
 * settled, or after `waitMs` with whatever resolves then (bundled while the
 * request is still out). A new revision or a late answer never swaps a form
 * being answered. `null` means wait; `release` lets the next opening resolve
 * afresh; `reload` refetches the origin's content and freezes the form anew.
 */
export function useOpenFeedbackForm(
  origin: FeedbackOrigin,
  open: boolean,
  waitMs: number = FORM_WAIT_MS
) {
  const live = useFeedbackForm(origin);
  const queryClient = useQueryClient();
  const [frozen, setFrozen] = useState<ResolvedFeedbackForm | null>(null);
  const [expired, setExpired] = useState(false);
  const [reloading, setReloading] = useState(false);
  const waiting = open && frozen === null && !reloading;

  if (waiting && (live.settled || expired)) {
    setFrozen(live.form);
    setExpired(false);
  }

  useEffect(() => {
    if (!waiting) return undefined;
    const timer = setTimeout(() => setExpired(true), waitMs);
    return () => clearTimeout(timer);
  }, [waiting, waitMs]);

  return {
    form: frozen,
    release: () => {
      setFrozen(null);
      setExpired(false);
    },
    reload: async () => {
      setReloading(true);
      setFrozen(null);
      try {
        await queryClient.fetchQuery({
          queryKey: live.contentKey,
          queryFn: live.readFresh,
          staleTime: 0,
          retry: false,
        });
      } catch {
        // A failed refetch keeps the cached form, which is the one the gateway
        // just refused; the bundled form is the way out.
        setFrozen(live.bundled);
      }
      setReloading(false);
    },
  };
}
