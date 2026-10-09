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
    <div className="flex basis-1/3 flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5">
      <p className="text-thanks font-semibold text-fg-strong">{copy.headline}</p>

      <div className="flex flex-1 items-center gap-3">
        <span
          aria-hidden
          className={cn('size-4 shrink-0 rounded-pill transition-colors', LAMP[level])}
        />
        <p className="text-label leading-snug text-fg-muted">{copy.levels[level]}</p>
      </div>
    </div>
  );
}
