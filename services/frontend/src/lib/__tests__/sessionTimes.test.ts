import { describe, expect, it } from 'vitest';
import { describeStart, durationMinutes } from '@/lib/sessionTimes';

/** Local wall-clock time in the browser's zone, which a null tenant zone formats in. */
const at = (year: number, month: number, day: number, hour: number, minute: number) =>
  new Date(year, month - 1, day, hour, minute);

describe('describeStart', () => {
  it('names the same calendar day', () => {
    const result = describeStart(
      at(2026, 8, 26, 14, 32).toISOString(),
      at(2026, 8, 26, 18, 0),
      'de-DE',
      null
    );
    expect(result).toEqual({ day: 'today', time: '14:32', label: '' });
  });

  it('names the previous calendar day, not a 24-hour span', () => {
    const result = describeStart(
      at(2026, 8, 25, 23, 50).toISOString(),
      at(2026, 8, 26, 0, 10),
      'de-DE',
      null
    );
    expect(result.day).toBe('yesterday');
    expect(result.time).toBe('23:50');
  });

  it('falls back to a short weekday inside the same week', () => {
    const result = describeStart(
      at(2026, 8, 24, 17, 50).toISOString(),
      at(2026, 8, 26, 9, 0),
      'de-DE',
      null
    );
    expect(result.day).toBe('other');
    expect(result.label).not.toBe('');
    expect(result.label.length).toBeLessThanOrEqual(4);
  });

  it('falls back to a date beyond a week', () => {
    const result = describeStart(
      at(2026, 8, 4, 8, 5).toISOString(),
      at(2026, 8, 26, 9, 0),
      'de-DE',
      null
    );
    expect(result.day).toBe('other');
    expect(result.label).toContain('04');
  });

  it('formats the time in the locale it is given', () => {
    const iso = at(2026, 8, 26, 14, 32).toISOString();
    expect(describeStart(iso, at(2026, 8, 26, 15, 0), 'en-US', null).time).toMatch(/2:32/);
  });
});

const BERLIN = 'Europe/Berlin';
const NEW_YORK = 'America/New_York';
const utc = (iso: string) => new Date(iso);

describe('describeStart in a tenant time zone', () => {
  // 23:55 on 8 October in Berlin (CEST), 17:55 in New York.
  const lateEvening = '2026-10-08T21:55:00Z';
  // 00:10 on 9 October in Berlin, still 18:10 on 8 October in New York.
  const afterBerlinMidnight = utc('2026-10-08T22:10:00Z');

  it('formats the clock time in the zone', () => {
    expect(describeStart(lateEvening, afterBerlinMidnight, 'de-DE', BERLIN).time).toBe('23:55');
    expect(describeStart(lateEvening, afterBerlinMidnight, 'de-DE', NEW_YORK).time).toBe('17:55');
  });

  it('counts calendar days in the zone, not in the browser', () => {
    expect(describeStart(lateEvening, afterBerlinMidnight, 'de-DE', BERLIN).day).toBe('yesterday');
    expect(describeStart(lateEvening, afterBerlinMidnight, 'de-DE', NEW_YORK).day).toBe('today');
  });

  it('names the weekday in the zone', () => {
    // Tuesday 00:30 in Berlin, Monday 18:30 in New York.
    const start = '2026-10-05T22:30:00Z';
    const now = utc('2026-10-08T12:00:00Z');
    // Prefixes only: ICU versions disagree on the trailing dot.
    expect(describeStart(start, now, 'de-DE', BERLIN).label).toMatch(/^Di/);
    expect(describeStart(start, now, 'de-DE', NEW_YORK).label).toMatch(/^Mo/);
  });

  it('dates an older session in the zone', () => {
    // 1 September 00:30 in Berlin, 31 August 18:30 in New York.
    const start = '2026-08-31T22:30:00Z';
    const now = utc('2026-10-08T12:00:00Z');
    expect(describeStart(start, now, 'de-DE', BERLIN).label).toBe('01.09.');
    expect(describeStart(start, now, 'de-DE', NEW_YORK).label).toBe('31.08.');
  });

  it('keeps yesterday across the autumn clock change', () => {
    // 23:30 CEST on 24 October to 23:30 CET on 25 October, a 25-hour day apart.
    const result = describeStart(
      '2026-10-24T21:30:00Z',
      utc('2026-10-25T22:30:00Z'),
      'de-DE',
      BERLIN
    );
    expect(result.day).toBe('yesterday');
  });

  it('keeps yesterday across the spring clock change', () => {
    // 23:30 CET on 28 March to 23:30 CEST on 29 March, a 23-hour day apart.
    const result = describeStart(
      '2026-03-28T22:30:00Z',
      utc('2026-03-29T21:30:00Z'),
      'de-DE',
      BERLIN
    );
    expect(result.day).toBe('yesterday');
  });

  it('keeps today through a 25-hour day', () => {
    // 00:30 CEST to 23:30 CET, both on 25 October.
    const result = describeStart(
      '2026-10-24T22:30:00Z',
      utc('2026-10-25T22:30:00Z'),
      'de-DE',
      BERLIN
    );
    expect(result.day).toBe('today');
  });

  it('uses the browser zone when the tenant has none', () => {
    const browser = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(describeStart(lateEvening, afterBerlinMidnight, 'de-DE', null)).toEqual(
      describeStart(lateEvening, afterBerlinMidnight, 'de-DE', browser)
    );
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
