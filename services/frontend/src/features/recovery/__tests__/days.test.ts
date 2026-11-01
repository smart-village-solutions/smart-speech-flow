import { describe, expect, it } from 'vitest';
import { dayRange, localDay, localMidnight } from '@/features/recovery/days';

describe('day range of the request form', () => {
  it('reads input days in local time, as the date field shows them', () => {
    const lateEvening = new Date(2026, 9, 29, 23, 30);
    expect(localDay(0, lateEvening)).toBe('2026-10-29');
    expect(localDay(-30, lateEvening)).toBe('2026-09-29');
    expect(localMidnight('2026-10-29')).toBe(new Date(2026, 9, 29).toISOString());
  });

  it('includes both chosen days, so a single day is a valid range', () => {
    expect(dayRange('2026-10-29', '2026-10-29')).toEqual({
      from: new Date(2026, 9, 29).toISOString(),
      to: new Date(2026, 9, 30).toISOString(),
    });
  });

  it('a cleared, malformed or reversed range is no range rather than an error', () => {
    expect(localMidnight('')).toBeNull();
    expect(dayRange('', '2026-10-29')).toBeNull();
    expect(dayRange('2026-10-29', '2026-1')).toBeNull();
    expect(dayRange('2026-10-30', '2026-10-29')).toBeNull();
  });
});
