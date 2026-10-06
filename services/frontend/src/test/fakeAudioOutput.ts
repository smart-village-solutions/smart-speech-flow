import { vi, type Mock } from 'vitest';
import type { AudioOutput } from '@/core/audio/audio-output';

/** An output whose unlocks a test can count; nothing reaches a real speaker. */
export function createFakeAudioOutput(): AudioOutput & { unlock: Mock<() => void> } {
  return {
    context: () => {
      throw new Error('Web Audio is unavailable');
    },
    unlock: vi.fn<() => void>(),
    ensureRunning: vi.fn().mockResolvedValue(true),
    setSounding: vi.fn(),
  };
}
