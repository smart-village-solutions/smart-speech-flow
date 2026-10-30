const DAY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

const pad = (value: number) => String(value).padStart(2, '0');

/** A date input's value for the local day `days` from today. */
export function localDay(days = 0, today: Date = new Date()): string {
  const at = new Date(today.getFullYear(), today.getMonth(), today.getDate() + days);
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

/**
 * The ISO instant of local midnight starting `day`, `offset` days later; null
 * for a cleared or malformed input, which a date field may hold mid-edit.
 */
export function localMidnight(day: string, offset = 0): string | null {
  const match = DAY_PATTERN.exec(day);
  if (match === null) return null;
  const at = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + offset);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}

/** From the first day's start to the end of the last: both chosen days count. */
export function dayRange(from: string, to: string): { from: string; to: string } | null {
  const start = localMidnight(from);
  const end = localMidnight(to, 1);
  return start === null || end === null || start >= end ? null : { from: start, to: end };
}
