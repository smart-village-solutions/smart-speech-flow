import { useEffect, useState } from 'react';
import { useServices } from '@/app/providers/services';
import { useGuestContent } from '@/features/content/useGuestContent';
import { consentCopy, type ConsentCopy } from './consentCopy';

interface Shown {
  key: string;
  copy: ConsentCopy;
}

/**
 * Guest content for the consent screen, which waits for it rather than swap one
 * legal text for another. The first copy shown is kept for the session and
 * language: the content once it settles, or the bundled text after the request
 * timeout. A late answer, a reconnect refetch or a new revision changes nothing.
 */
export function useConsentContent(
  sessionId: string | undefined,
  language: string | undefined
): { ready: boolean; copy: ConsentCopy } {
  const { config } = useServices();
  const { content, settled } = useGuestContent(sessionId, language);
  const key = `${sessionId ?? ''}/${language ?? ''}`;
  const [shown, setShown] = useState<Shown | null>(null);
  const current = shown?.key === key ? shown.copy : undefined;

  if (current === undefined && settled) setShown({ key, copy: consentCopy(content) });

  useEffect(() => {
    if (current !== undefined) return undefined;
    const timer = setTimeout(
      () =>
        setShown((previous) =>
          previous?.key === key ? previous : { key, copy: consentCopy(undefined) }
        ),
      config.requestTimeoutMs
    );
    return () => clearTimeout(timer);
  }, [current, key, config.requestTimeoutMs]);

  return current === undefined
    ? { ready: false, copy: consentCopy(undefined) }
    : { ready: true, copy: current };
}
