import { useCallback, useEffect, useState } from 'react';
import { useServices } from '@/app/providers/services';
import { sha256Hex } from '@/core/crypto/digest';
import type { ConsentText } from '@/domain/recording/recordingSession.types';

interface Loaded {
  text: ConsentText;
  /** SHA-256 of `text.html`, the very string rendered: what a yes sends back. */
  hash: string;
}

/**
 * The open question's consent text, fetched from the gateway and hashed as
 * served (spec §6). It is fetched again when the guest changes language, and
 * on `reload`, after the gateway said the text changed under the guest.
 */
export function useConsentText(
  sessionId: string,
  requestId: string | null,
  language: string | null
) {
  const { recordingSession } = useServices();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failedFor, setFailedFor] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (requestId === null) return;
    let cancelled = false;
    void (async () => {
      try {
        const text = await recordingSession.consentText(sessionId);
        const hash = await sha256Hex(text.html);
        if (!cancelled) setLoaded({ text, hash });
      } catch {
        if (!cancelled) setFailedFor(requestId);
      }
    })();
    return () => {
      cancelled = true;
    };
    // The language is a dependency only: the gateway serves the session's language.
  }, [attempt, language, recordingSession, requestId, sessionId]);

  // The text in hand is no longer the one to answer; until the new one arrives
  // there is nothing to say yes to.
  const reload = useCallback(() => {
    setLoaded(null);
    setFailedFor(null);
    setAttempt((count) => count + 1);
  }, []);

  // A text fetched for an earlier question is never shown for this one.
  const current = loaded !== null && loaded.text.requestId === requestId ? loaded : null;
  return { consent: current, failed: requestId !== null && failedFor === requestId, reload };
}
