import { useEffect, useState } from 'react';
import type { GuestContent, LegalInformation } from '@/domain/content/content.types';
import { useServices } from '@/app/providers/services';
import { useGuestContent } from '@/features/content/useGuestContent';

interface EntryContent {
  legalInformation: LegalInformation | null | undefined;
}

interface Shown extends EntryContent {
  key: string;
}

function entryContent(content: GuestContent | undefined): EntryContent {
  return {
    legalInformation: content?.legalInformation,
  };
}

/**
 * Keep reference wording stable for the session and route language once content
 * settles or times out. Late content and reconnects cannot replace that snapshot.
 * The ordinary introduction itself comes exclusively from the UI catalogues.
 */
export function useConsentContent(
  sessionId: string | undefined,
  language: string | undefined
): EntryContent & { ready: boolean } {
  const { config } = useServices();
  const { content, settled } = useGuestContent(sessionId, language);
  const key = `${sessionId ?? ''}/${language ?? ''}`;
  const [shown, setShown] = useState<Shown | null>(null);
  const current = shown?.key === key ? shown : undefined;

  if (current === undefined && settled) setShown({ key, ...entryContent(content) });

  useEffect(() => {
    if (current !== undefined) return undefined;
    const timer = setTimeout(
      () =>
        setShown((previous) =>
          previous?.key === key ? previous : { key, ...entryContent(undefined) }
        ),
      config.requestTimeoutMs
    );
    return () => clearTimeout(timer);
  }, [current, key, config.requestTimeoutMs]);

  return current === undefined
    ? { ready: false, ...entryContent(undefined) }
    : { ...current, ready: true };
}
