export type StartDay = 'today' | 'yesterday' | 'other';

export interface StartDescriptor {
  day: StartDay;
  /** Localised hour and minute. */
  time: string;
  /** Short weekday or date for `other`; empty for the two named days. */
  label: string;
}

const DAY_MS = 86_400_000;
const MINUTE_MS = 60_000;
const WEEK_DAYS = 7;

/** Local midnight, so "yesterday" means the previous date and not 24 hours ago. */
function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/**
 * The session list's "Gestartet" column. The copy stays with the caller: this
 * returns which of the three shapes applies and the parts to interpolate.
 */
export function describeStart(iso: string, now: Date, locale: string): StartDescriptor {
  const start = new Date(iso);
  const time = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(
    start
  );
  // Rounded, not truncated: a clock change makes the span between two local
  // midnights 23 or 25 hours, which integer division would read as a day off.
  const days = Math.round((startOfDay(now) - startOfDay(start)) / DAY_MS);

  if (days <= 0) {
    return { day: 'today', time, label: '' };
  }
  if (days === 1) {
    return { day: 'yesterday', time, label: '' };
  }

  const label =
    days < WEEK_DAYS
      ? new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(start)
      : new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit' }).format(start);

  return { day: 'other', time, label };
}

/** Whole minutes. The caller passes now as the end while a session is still open. */
export function durationMinutes(startIso: string, endIso: string): number {
  const span = new Date(endIso).getTime() - new Date(startIso).getTime();
  return Math.max(0, Math.round(span / MINUTE_MS));
}
