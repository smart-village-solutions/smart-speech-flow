import { useCallback, useEffect, useRef, useState } from 'react';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import { type EditableFinding, editable } from './editable';
import type { ReviewState } from './openReview';
import { sealNotes } from './sealNotes';

type Ready = Extract<ReviewState, { status: 'ready' }>;

/** The reviewer's notes in memory, saved encrypted on demand and when the screen closes. */
export function useReviewDraft(state: Ready) {
  const { reviews, archiveCrypto } = useServices();
  const [findings, setFindings] = useState(
    () => new Map([...state.draft.findings].map(([entryId, list]) => [entryId, list.map(editable)]))
  );
  const [overall, setOverall] = useState(state.draft.overall);
  const [dirty, setDirty] = useState(false);
  const latest = useRef({ findings, overall, dirty });
  useEffect(() => {
    latest.current = { findings, overall, dirty };
  }, [findings, overall, dirty]);

  const seal = useCallback(async () => {
    const identity = getAdminIdentity();
    if (identity === null) throw new Error('signed out');
    const { findings: current, overall: text } = latest.current;
    return sealNotes({
      crypto: archiveCrypto,
      tenantId: identity.tenantId,
      review: state.review,
      keys: state.ready.keys,
      findings: current,
      overall: text,
    });
  }, [archiveCrypto, state]);

  const save = useCallback(async () => {
    await reviews.saveDraft(state.review.record.verificationId, await seal());
    setDirty(false);
  }, [reviews, seal, state]);

  // Set once the record is decided or declined: nothing is left to save into.
  const closed = useRef(false);
  useEffect(() => {
    const flush = () => {
      if (latest.current.dirty && !closed.current) save().catch(() => undefined);
    };
    globalThis.addEventListener('pagehide', flush);
    return () => {
      globalThis.removeEventListener('pagehide', flush);
      flush();
    };
  }, [save]);

  return {
    findings,
    overall,
    dirty,
    seal,
    save,
    close: () => {
      closed.current = true;
    },
    setEntry: (entryId: string, next: EditableFinding[]) => {
      setFindings((previous) => new Map(previous).set(entryId, next));
      setDirty(true);
    },
    setOverall: (text: string) => {
      setOverall(text);
      setDirty(true);
    },
  };
}

export type ReviewDraftState = ReturnType<typeof useReviewDraft>;
