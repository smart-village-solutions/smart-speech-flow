import type { ReactNode } from 'react';
import { SiteLegalLinks } from '@/features/content/SiteLegalLinks';
import { ScreenShell } from '@/ui/patterns/ScreenShell';

/** A loading or error state outside any screen; it still carries the legal links. */
export function RouteState({ children }: Readonly<{ children?: ReactNode }>) {
  return (
    <ScreenShell>
      <main className="flex flex-1 items-center justify-center px-5">{children}</main>
      <SiteLegalLinks className="px-5 pt-4 pb-legal-end" />
    </ScreenShell>
  );
}
