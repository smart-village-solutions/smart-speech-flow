import { vi } from 'vitest';

interface FakeBufferSource {
  buffer: { duration: number } | null;
  onended: (() => void) | null;
  offset: number;
  stopped: boolean;
  connect: ReturnType<typeof vi.fn>;
  start: (when?: number, offset?: number) => void;
  stop: () => void;
  /** The clip reaching its natural end. */
  finish: () => void;
}

/**
 * Enough of an AudioContext to drive the output and the player. jsdom has no
 * Web Audio at all. `resumeBehaviour` decides what a resume does: run, as a
 * gesture-unlocked context would, or hang, as iOS does without a gesture.
 */
export function createFakeAudioContext() {
  const started: FakeBufferSource[] = [];

  const context = {
    state: 'suspended',
    currentTime: 0,
    sampleRate: 44100,
    destination: {},
    resumeBehaviour: 'run' as 'run' | 'hang',
    started,

    resume: vi.fn(() => {
      if (context.resumeBehaviour === 'hang') {
        return new Promise<void>(() => undefined);
      }
      // Asynchronous, as in browsers: the state only changes once the promise settles.
      return Promise.resolve().then(() => {
        context.state = 'running';
      });
    }),

    decodeAudioData: vi.fn<(bytes: ArrayBuffer) => Promise<{ duration: number }>>(async () => ({
      duration: 10,
    })),

    createBuffer: (_channels: number, length: number, rate: number) => ({
      duration: length / rate,
    }),

    createBufferSource: (): FakeBufferSource => {
      const source: FakeBufferSource = {
        buffer: null,
        onended: null,
        offset: 0,
        stopped: false,
        connect: vi.fn(),
        start: (...args: [when?: number, offset?: number]) => {
          source.offset = args[1] ?? 0;
          started.push(source);
        },
        // Fired synchronously, which is harsher than a browser: code that
        // forgets to detach before stopping sees a spurious end straight away.
        stop: () => {
          source.stopped = true;
          source.onended?.();
        },
        finish: () => source.onended?.(),
      };
      return source;
    },

    /** The newest source started, if any. */
    last: (): FakeBufferSource | undefined => started.at(-1),
  };

  return context;
}

export const asAudioContext = (fake: ReturnType<typeof createFakeAudioContext>) =>
  fake as unknown as AudioContext;
