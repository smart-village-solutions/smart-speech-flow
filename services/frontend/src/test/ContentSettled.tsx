import { useGuestContent } from '@/features/content/useGuestContent';
import { useGuestLanguages } from '@/features/content/useGuestLanguages';
import { usePublicContent } from '@/features/content/usePublicContent';

/**
 * Renders once installation content has arrived or failed. Beside a screen it
 * shares that screen's query, so finding it means the screen has already
 * re-rendered with whatever content there is.
 */
export function ContentSettled() {
  return usePublicContent().settled ? <span data-testid="public-content-settled" hidden /> : null;
}

interface GuestContentSettledProps {
  sessionId: string;
  language: string;
}

/** The same for a guest screen: the session's language list and one language's content. */
export function GuestContentSettled({ sessionId, language }: Readonly<GuestContentSettledProps>) {
  const languagesIdle = useGuestLanguages(sessionId).fetchStatus === 'idle';
  const contentSettled = useGuestContent(sessionId, language).settled;
  return languagesIdle && contentSettled ? (
    <span data-testid="guest-content-settled" hidden />
  ) : null;
}
