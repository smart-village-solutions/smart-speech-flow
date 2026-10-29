import { clockTime, durationMinutes } from '@/lib/sessionTimes';

/** Day of an instant, in the browser's time zone. */
export function formatDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(new Date(iso));
}

/** Hour, minute and second: entries of one conversation are seconds apart. */
export function formatTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(iso));
}

export function formatTimeRange(startIso: string, endIso: string, locale: string): string {
  return `${clockTime(new Date(startIso).getTime(), locale)}–${clockTime(new Date(endIso).getTime(), locale)}`;
}

export function minutesBetween(startIso: string, endIso: string): number {
  return durationMinutes(startIso, endIso);
}
