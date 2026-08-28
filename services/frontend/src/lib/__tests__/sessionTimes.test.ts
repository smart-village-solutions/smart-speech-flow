import { describe, expect, it } from 'vitest';
import { describeStart, durationMinutes } from '@/lib/sessionTimes';

/** Local wall-clock time, so the expectations do not depend on the runner's TZ. */
const at = (year: number, month: number, day: number, hour: number, minute: number) =>
  new Date(year, month - 1, day, hour, minute);

describe('describeStart', () => {
  it('names the same calendar day', () => {
    const result = describeStart(
      at(2026, 8, 26, 14, 32).toISOString(),
      at(2026, 8, 26, 18, 0),
      'de-DE'
    );
    expect(result).toEqual({ day: 'today', time: '14:32', label: '' });
  });

  it('names the previous calendar day, not a 24-hour span', () => {
    const result = describeStart(
      at(2026, 8, 25, 23, 50).toISOString(),
      at(2026, 8, 26, 0, 10),
      'de-DE'
    );
    expect(result.day).toBe('yesterday');
    expect(result.time).toBe('23:50');
  });

  it('falls back to a short weekday inside the same week', () => {
    const result = describeStart(
      at(2026, 8, 24, 17, 50).toISOString(),
      at(2026, 8, 26, 9, 0),
      'de-DE'
    );
    expect(result.day).toBe('other');
    expect(result.label).not.toBe('');
    expect(result.label.length).toBeLessThanOrEqual(4);
  });

  it('falls back to a date beyond a week', () => {
    const result = describeStart(
      at(2026, 8, 4, 8, 5).toISOString(),
      at(2026, 8, 26, 9, 0),
      'de-DE'
    );
    expect(result.day).toBe('other');
    expect(result.label).toContain('04');
  });

  it('formats the time in the locale it is given', () => {
    const iso = at(2026, 8, 26, 14, 32).toISOString();
    expect(describeStart(iso, at(2026, 8, 26, 15, 0), 'en-US').time).toMatch(/2:32/);
  });
});

describe('durationMinutes', () => {
  it('rounds to whole minutes', () => {
    expect(
      durationMinutes(at(2026, 8, 26, 9, 0).toISOString(), at(2026, 8, 26, 9, 14).toISOString())
    ).toBe(14);
  });

  it('rounds a part-minute tail to the nearest minute', () => {
    const start = at(2026, 8, 26, 9, 0);
    const end = new Date(start.getTime() + 100_000);
    expect(durationMinutes(start.toISOString(), end.toISOString())).toBe(2);
  });

  it('never reports a negative duration', () => {
    expect(
      durationMinutes(at(2026, 8, 26, 9, 14).toISOString(), at(2026, 8, 26, 9, 0).toISOString())
    ).toBe(0);
  });
});
