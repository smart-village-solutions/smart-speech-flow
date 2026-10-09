import { useEffect, useState, type ReactNode } from 'react';
import { useFavicon } from '@/ui/hooks/useFavicon';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { CONTENT_WAIT_MS } from './contentQuery';
import { usePublicContent } from './usePublicContent';

interface PublicContentGateProps {
  children: ReactNode;
  waitMs?: number;
}

/**
 * Requests installation content at app start and holds the first paint until it
 * settles, for at most `waitMs`, so the start page and the legal links do not
 * swap from bundled to Studio copy. Later screens read the cached query. It also
 * applies the installation icon as the favicon.
 */
export function PublicContentGate({
  children,
  waitMs = CONTENT_WAIT_MS,
}: Readonly<PublicContentGateProps>) {
  const { content, settled } = usePublicContent();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setOpen(true), waitMs);
    return () => clearTimeout(timer);
  }, [waitMs]);

  // Once open it stays open: a later refetch must not unmount the screens.
  if (settled && !open) setOpen(true);

  useFavicon(content?.branding.icon?.url ?? null);

  // The empty shell paints the themed page background while it waits.
  return open || settled ? children : <ScreenShell>{null}</ScreenShell>;
}
