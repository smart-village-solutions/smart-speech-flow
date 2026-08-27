import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface ScreenShellProps {
  children: ReactNode;
  className?: string;
}

/**
 * The page background and the 800px centred column every screen sits in.
 *
 * The height is `dvh`, not the export's `100vh`. `vh` is the large viewport —
 * the page as it would be with the mobile browser's toolbar hidden — so on a
 * phone or tablet a `100vh` shell hangs below the fold by the height of that
 * toolbar, the document scrolls, and whatever is anchored to the shell's bottom
 * goes with it. That is what buried the conversation screen's buttons.
 */
export function ScreenShell({ children, className }: Readonly<ScreenShellProps>) {
  return (
    <div
      data-screen-shell=""
      className="min-h-dvh w-full bg-surface-page font-sans text-fg-strong transition-colors duration-300"
    >
      <div
        className={cn('relative mx-auto flex min-h-dvh w-full max-w-app flex-col', className)}
      >
        {children}
      </div>
    </div>
  );
}
