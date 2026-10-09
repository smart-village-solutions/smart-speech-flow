import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import { CONTENT_WAIT_MS } from '@/features/content/contentQuery';
import type { ResolvedFeedbackForm } from './resolveFeedbackForm';
import { useFeedbackForm, type LiveFeedbackForm } from './useFeedbackForm';

/**
 * `opening`: freeze once content settles or the wait expires. `reloading`: a
 * fresh read after a 409 is out; the wait gives up on it. `reloaded`: freeze
 * what it brought, unless it is the revision the gateway refused. `bundled`:
 * the reload failed or gave up.
 */
type Phase =
  | { kind: 'opening' }
  | { kind: 'reloading' }
  | { kind: 'reloaded'; refused: string | null }
  | { kind: 'bundled' };

const OPENING: Phase = { kind: 'opening' };
const BUNDLED: Phase = { kind: 'bundled' };

function formToFreeze(
  phase: Phase,
  live: LiveFeedbackForm,
  expired: boolean
): ResolvedFeedbackForm | null {
  switch (phase.kind) {
    case 'opening':
      return live.settled || expired ? live.resolve() : null;
    case 'reloading':
      return null;
    case 'reloaded': {
      // The same revision again means client and gateway disagree on its rules;
      // the bundled form's rules are shared with the gateway.
      const form = live.resolve();
      return form.revision !== null && form.revision === phase.refused
        ? live.resolveBundled()
        : form;
    }
    case 'bundled':
      return live.resolveBundled();
  }
}

/**
 * The form an open sheet shows, frozen the moment it is known: once content has
 * settled, or after `waitMs` with whatever resolves then (bundled while the
 * request is still out). A new revision or a late answer never swaps a form
 * being answered. `null` means wait; `release` lets the next opening resolve
 * afresh; `reload` reads the origin's content past every cache and freezes anew.
 */
export function useOpenFeedbackForm(
  origin: FeedbackOrigin,
  open: boolean,
  waitMs: number = CONTENT_WAIT_MS
) {
  const live = useFeedbackForm(origin, open);
  const queryClient = useQueryClient();
  const [frozen, setFrozen] = useState<ResolvedFeedbackForm | null>(null);
  const [expired, setExpired] = useState(false);
  const [phase, setPhase] = useState<Phase>(OPENING);
  // Bumped by every release and reload, so a read that outlives its opening is ignored.
  const generation = useRef(0);
  const pending = open && frozen === null;
  const reloading = phase.kind === 'reloading';

  const next = pending ? formToFreeze(phase, live, expired) : null;
  if (next !== null) {
    setFrozen(next);
    setExpired(false);
    setPhase(OPENING);
  }

  useEffect(() => {
    if (!pending) return undefined;
    const timer = setTimeout(() => {
      if (!reloading) {
        setExpired(true);
        return;
      }
      generation.current += 1;
      setPhase(BUNDLED);
    }, waitMs);
    return () => clearTimeout(timer);
  }, [pending, reloading, waitMs]);

  return {
    form: frozen,
    release: () => {
      generation.current += 1;
      setFrozen(null);
      setExpired(false);
      setPhase(OPENING);
    },
    reload: async () => {
      generation.current += 1;
      const mine = generation.current;
      const refused = frozen?.revision ?? null;
      setFrozen(null);
      setPhase({ kind: 'reloading' });
      let after: Phase = { kind: 'reloaded', refused };
      try {
        // A refetch already in flight would be shared, and it reads through the browser cache.
        await queryClient.cancelQueries({ queryKey: live.contentKey });
        await queryClient.fetchQuery({
          queryKey: live.contentKey,
          queryFn: live.readFresh,
          staleTime: 0,
          retry: false,
        });
      } catch {
        // A failed refetch keeps the cached form, which is the one the gateway refused.
        after = BUNDLED;
      }
      if (generation.current === mine) setPhase(after);
    },
  };
}
