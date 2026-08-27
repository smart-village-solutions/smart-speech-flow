import { describe, expect, it, vi } from 'vitest';
import { BAR_COUNT, LEAD_BARS, WAVE_HEIGHTS, activeBarsForProgress } from '@/core/audio/waveform';

describe('WAVE_HEIGHTS', () => {
  it('has one entry per bar', () => {
    expect(WAVE_HEIGHTS).toHaveLength(BAR_COUNT);
  });

  it('leaves the lead-in bars flat, matching the export', () => {
    expect(WAVE_HEIGHTS.slice(0, LEAD_BARS)).toEqual(new Array(LEAD_BARS).fill(0));
  });

  it('keeps every other bar inside the export range of 0.25 to 1', () => {
    for (const height of WAVE_HEIGHTS.slice(LEAD_BARS)) {
      expect(height).toBeGreaterThanOrEqual(0.25);
      expect(height).toBeLessThanOrEqual(1);
    }
  });

  it('is deterministic, unlike the export Math.random version', async () => {
    vi.resetModules();
    const again = await import('@/core/audio/waveform');
    expect(again.WAVE_HEIGHTS).toEqual(WAVE_HEIGHTS);
    expect(again.WAVE_HEIGHTS).not.toBe(WAVE_HEIGHTS);
  });
});

describe('activeBarsForProgress', () => {
  it('fills no bars at the start and all bars at the end', () => {
    expect(activeBarsForProgress(0)).toBe(0);
    expect(activeBarsForProgress(1)).toBe(BAR_COUNT);
  });

  it('fills proportionally in between', () => {
    expect(activeBarsForProgress(0.5)).toBe(25);
  });

  it('clamps out-of-range input', () => {
    expect(activeBarsForProgress(-1)).toBe(0);
    expect(activeBarsForProgress(2)).toBe(BAR_COUNT);
  });
});
