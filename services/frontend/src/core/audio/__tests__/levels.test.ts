import { describe, expect, it } from 'vitest';
import {
  MIN_BAR_HEIGHT,
  heightFromRms,
  peaksFromSamples,
  rms,
} from '@/core/audio/levels';

/** A block of `count` samples at a constant absolute amplitude. */
function block(count: number, amplitude: number): number[] {
  return Array.from({ length: count }, (_, index) => (index % 2 === 0 ? amplitude : -amplitude));
}

describe('rms', () => {
  it('is zero for silence', () => {
    expect(rms(new Float32Array(64))).toBe(0);
  });

  it('is the amplitude for a square wave', () => {
    expect(rms(new Float32Array(block(64, 0.5)))).toBeCloseTo(0.5, 5);
  });

  it('is zero for an empty window rather than NaN', () => {
    expect(rms(new Float32Array(0))).toBe(0);
  });
});

describe('heightFromRms', () => {
  it('never returns a bar too short to see', () => {
    expect(heightFromRms(0)).toBe(MIN_BAR_HEIGHT);
  });

  it('never exceeds the full bar height', () => {
    expect(heightFromRms(1)).toBe(1);
    expect(heightFromRms(5)).toBe(1);
  });

  it('rises with loudness', () => {
    const quiet = heightFromRms(0.02);
    const normal = heightFromRms(0.1);
    const loud = heightFromRms(0.4);

    expect(quiet).toBeLessThan(normal);
    expect(normal).toBeLessThan(loud);
  });
});

describe('peaksFromSamples', () => {
  it('returns exactly the number of bars asked for', () => {
    expect(peaksFromSamples(new Float32Array(block(4410, 0.3)), 50)).toHaveLength(50);
  });

  it('follows the shape of the clip', () => {
    // Loud first half, silent second half.
    const samples = new Float32Array([...block(500, 0.8), ...new Array(500).fill(0)]);

    const peaks = peaksFromSamples(samples, 10);

    expect(peaks.slice(0, 5).every((peak) => peak > 0.9)).toBe(true);
    expect(peaks.slice(5)).toEqual(new Array(5).fill(MIN_BAR_HEIGHT));
  });

  it('normalises the loudest bar to full height, however quiet the clip', () => {
    const samples = new Float32Array([...block(500, 0.02), ...block(500, 0.01)]);

    const peaks = peaksFromSamples(samples, 2);

    expect(Math.max(...peaks)).toBe(1);
  });

  it('renders silence as an unbroken floor rather than nothing', () => {
    expect(peaksFromSamples(new Float32Array(500), 10)).toEqual(new Array(10).fill(MIN_BAR_HEIGHT));
  });

  it('survives a clip shorter than the bar count', () => {
    const peaks = peaksFromSamples(new Float32Array(block(3, 0.5)), 10);

    expect(peaks).toHaveLength(10);
    expect(peaks.every((peak) => peak >= MIN_BAR_HEIGHT && peak <= 1)).toBe(true);
  });

  it('has no bars at all for an empty clip', () => {
    expect(peaksFromSamples(new Float32Array(0), 0)).toEqual([]);
  });
});
