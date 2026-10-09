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

/**
 * The calendar date in `timeZone` as UTC midnight. Two of these are always a
 * whole number of 24-hour days apart, whatever clock change lies between them,
 * so "yesterday" means the previous date and not 24 hours ago.
 */
function calendarDay(date: Date, timeZone: string | undefined): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((entry) => entry.type === type)?.value);
  return Date.UTC(part('year'), part('month') - 1, part('day'));
}

/**
 * The session list's "Gestartet" column, in the tenant's time zone; null means
 * the browser's. The copy stays with the caller: this returns which of the
 * three shapes applies and the parts to interpolate.
 */
export function describeStart(
  iso: string,
  now: Date,
  locale: string,
  timeZone: string | null
): StartDescriptor {
  const zone = timeZone ?? undefined;
  const start = new Date(iso);
  const format = (options: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat(locale, { ...options, timeZone: zone }).format(start);
  const time = format({ hour: '2-digit', minute: '2-digit' });
  const days = (calendarDay(now, zone) - calendarDay(start, zone)) / DAY_MS;

  if (days <= 0) {
    return { day: 'today', time, label: '' };
  }
  if (days === 1) {
    return { day: 'yesterday', time, label: '' };
  }

  const label =
    days < WEEK_DAYS ? format({ weekday: 'short' }) : format({ day: '2-digit', month: '2-digit' });

  return { day: 'other', time, label };
}

/** Whole minutes. The caller passes now as the end while a session is still open. */
export function durationMinutes(startIso: string, endIso: string): number {
  const span = new Date(endIso).getTime() - new Date(startIso).getTime();
  return Math.max(0, Math.round(span / MINUTE_MS));
}
