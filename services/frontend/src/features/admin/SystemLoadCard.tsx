import { cn } from '@/lib/cn';
import type { SystemLoadLevel } from '@/domain/health/health.types';
import type { LoadCopy } from '@/features/content/staffCopy';
import { useSystemLoad } from './useSystemLoad';

/** The lamp is theme-independent by design; see SCREEN_SPECS "Traffic-light states". */
const LAMP: Record<SystemLoadLevel, string> = {
  ok: 'bg-status-ok shadow-lamp-ok',
  delayed: 'bg-status-warn shadow-lamp-warn',
  unavailable: 'bg-status-down shadow-lamp-down',
  unknown: 'bg-status-idle',
};

interface SystemLoadCardProps {
  copy: LoadCopy;
}

export function SystemLoadCard({ copy }: Readonly<SystemLoadCardProps>) {
  const { data, isError } = useSystemLoad();
  const level: SystemLoadLevel = isError ? 'unknown' : (data?.level ?? 'unknown');

  return (
    <div className="flex flex-col gap-1.5 self-start rounded-xl border border-border-card bg-surface-card px-4 py-3 md:w-56">
      <p className="text-label font-semibold text-fg-strong">{copy.headline}</p>

      <div className="flex items-center gap-2.5">
        <span
          aria-hidden
          className={cn('size-2.5 shrink-0 rounded-pill transition-colors', LAMP[level])}
        />
        <p className="text-label leading-snug text-fg-muted">{copy.levels[level]}</p>
      </div>
    </div>
  );
}
