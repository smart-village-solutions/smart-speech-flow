import { useEffect, useState } from 'react';
import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import type { LinkDetails } from '@/domain/recording/recording.types';

export type ConfirmationError = 'missing' | 'invalid' | 'expired' | 'ceremony' | 'failed';
export type ConfirmationOutcome =
  | { kind: 'confirmed'; fingerprintDisplay: string }
  | { kind: 'declined' };

const CODES: Record<string, ConfirmationError> = {
  LINK_INVALID: 'invalid',
  LINK_EXPIRED: 'expired',
  CEREMONY_IN_PROGRESS: 'ceremony',
};

function confirmationError(caught: unknown): ConfirmationError {
  const code = caught instanceof AppError ? caught.serverCode : undefined;
  return (code !== undefined && CODES[code]) || 'failed';
}

/** The link's token, from the fragment: it never reaches a server log or a Referer. */
function readToken(): string | null {
  const token = window.location.hash.replace(/^#/, '');
  return token === '' ? null : token;
}

/** The mailed link of a re-enrolment (spec §9.9): look it up, then confirm or decline. */
export function useKeyConfirmation() {
  const { keyConfirmation } = useServices();
  const [token] = useState(readToken);
  const [details, setDetails] = useState<LinkDetails | null>(null);
  const [error, setError] = useState<ConfirmationError | null>(token === null ? 'missing' : null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<ConfirmationOutcome | null>(null);
  // The fragment is gone after the first read, so a failed lookup is retried from here.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
  }, []);

  useEffect(() => {
    if (token === null) return;
    let cancelled = false;
    keyConfirmation.lookup(token).then(
      (found) => {
        if (!cancelled) setDetails(found);
      },
      (caught: unknown) => {
        if (!cancelled) setError(confirmationError(caught));
      }
    );
    return () => {
      cancelled = true;
    };
  }, [keyConfirmation, token, attempt]);

  const act = async (step: (token: string) => Promise<ConfirmationOutcome>) => {
    if (token === null || busy) return;
    setBusy(true);
    setError(null);
    try {
      setOutcome(await step(token));
    } catch (caught) {
      const reason = confirmationError(caught);
      setError(reason);
      // A used or lapsed link has nothing left to show.
      if (reason === 'invalid' || reason === 'expired') setDetails(null);
    } finally {
      setBusy(false);
    }
  };

  return {
    details,
    error,
    busy,
    outcome,
    retry: () => {
      setError(null);
      setAttempt((count) => count + 1);
    },
    confirm: () =>
      act(async (link) => {
        const done = await keyConfirmation.confirm(link);
        return { kind: 'confirmed', fingerprintDisplay: done.fingerprintDisplay };
      }),
    decline: () =>
      act(async (link) => {
        await keyConfirmation.decline(link);
        return { kind: 'declined' };
      }),
  };
}
