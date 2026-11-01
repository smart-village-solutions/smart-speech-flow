import { useEffect, useState } from 'react';
import type { GuestContent, LegalInformation } from '@/domain/content/content.types';
import { useServices } from '@/app/providers/services';
import { useGuestContent } from '@/features/content/useGuestContent';
import { consentCopy, type ConsentCopy } from './consentCopy';

interface EntryContent {
  copy: ConsentCopy;
  legalInformation: LegalInformation | null | undefined;
  documentationInformation: LegalInformation | null | undefined;
}

interface Shown extends EntryContent {
  key: string;
}

function entryContent(content: GuestContent | undefined): EntryContent {
  return {
    copy: consentCopy(content),
    legalInformation: content?.legalInformation,
    // Explicit null is authoritative; only older servers need the reference fallback.
    documentationInformation:
      content?.documentationInformation !== undefined
        ? content.documentationInformation
        : content?.legalInformation,
  };
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
