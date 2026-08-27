import { vi } from 'vitest';
import type { Clip, ClipLoader } from '@/core/audio/clips';
import { BAR_COUNT } from '@/core/audio/waveform';

export interface FakeClipLoader extends ClipLoader {
  /** Give a url a shape; without one, loading it rejects. */
  provide: (url: string, peaks: number[]) => void;
  loaded: string[];
}

/** Even bars tall, odd bars short — an obviously non-decorative shape. */
export function stripedPeaks(bars = BAR_COUNT): number[] {
  return Array.from({ length: bars }, (_, index) => (index % 2 === 0 ? 1 : 0.1));
}

export function createFakeClipLoader(): FakeClipLoader {
  const clips = new Map<string, Clip>();
  const loaded: string[] = [];

  return {
    loaded,
    provide(url, peaks) {
      clips.set(url, { objectUrl: `blob:${url}`, peaks });
    },
    load: vi.fn(async (url: string) => {
      loaded.push(url);
      const clip = clips.get(url);
      if (clip === undefined) {
        throw new Error(`no clip for ${url}`);
      }
      return clip;
    }),
    peek: (url: string) => clips.get(url) ?? null,
    dispose: vi.fn(),
  };
}
