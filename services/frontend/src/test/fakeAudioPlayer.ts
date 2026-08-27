import { act } from '@testing-library/react';
import { vi } from 'vitest';
import type { AudioPlayerPort } from '@/core/audio/player.port';

export interface FakeAudioPlayer {
  port: AudioPlayerPort;
  /** Urls passed to play(), in order. */
  played: string[];
  stop: ReturnType<typeof vi.fn>;
  /** Resolve the pending play() — the clip is now audible. */
  started: () => Promise<void>;
  /** Reject the pending play(), as a browser refusing autoplay does. */
  rejected: (message?: string) => Promise<void>;
  end: () => Promise<void>;
  fail: () => Promise<void>;
  progress: (fraction: number) => Promise<void>;
}

/** A player whose promises and events a test drives by hand. */
export function createFakeAudioPlayer(): FakeAudioPlayer {
  const handlers = {
    progress: [] as ((fraction: number) => void)[],
    ended: [] as (() => void)[],
    error: [] as (() => void)[],
  };
  const played: string[] = [];
  let settle: { resolve: () => void; reject: (error: Error) => void } | null = null;

  const listen = <T>(list: T[], handler: T) => {
    list.push(handler);
    return () => {
      list.splice(list.indexOf(handler), 1);
    };
  };

  const stop = vi.fn();

  const port: AudioPlayerPort = {
    play: vi.fn((url: string) => {
      played.push(url);
      return new Promise<void>((resolve, reject) => {
        settle = { resolve, reject };
      });
    }),
    stop,
    onProgress: (handler) => listen(handlers.progress, handler),
    onEnded: (handler) => listen(handlers.ended, handler),
    onError: (handler) => listen(handlers.error, handler),
  };

  const fire = async (run: () => void) => {
    await act(async () => {
      run();
    });
  };

  return {
    port,
    played,
    stop,
    started: () => fire(() => settle?.resolve()),
    rejected: (message = 'NotAllowedError') => fire(() => settle?.reject(new Error(message))),
    end: () => fire(() => handlers.ended.forEach((handler) => handler())),
    fail: () => fire(() => handlers.error.forEach((handler) => handler())),
    progress: (fraction) => fire(() => handlers.progress.forEach((handler) => handler(fraction))),
  };
}
