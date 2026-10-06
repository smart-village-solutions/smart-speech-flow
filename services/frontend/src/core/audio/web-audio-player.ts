import type { AudioOutput } from './audio-output';
import type { AudioPlayerPort } from './player.port';

const PROTECTED_AUDIO = /^(?:https?:\/\/[^/]+)?\/api\/(?:admin|customer)\//;
const PROGRESS_INTERVAL_MS = 250;
// Decoded PCM is several times the size of the WAV the loader already holds, so
// only the clips most likely to be replayed stay decoded; older ones decode again.
const DECODED_CLIPS = 8;

const superseded = () => new DOMException('Playback was superseded', 'AbortError');

const fetchObjectUrl = async (url: string) => (await fetch(url)).arrayBuffer();

/**
 * Plays clips through the shared AudioContext rather than an `<audio>` element,
 * so a clip can start with no gesture once the context is unlocked — which is
 * what lets an arriving message autoplay on iOS. See `AudioOutput`.
 *
 * Takes the in-memory object url the clip loader produced, never a gateway url:
 * protected audio has to be fetched with credentials, which only the loader has.
 */
export function createWebAudioPlayer(
  output: AudioOutput,
  fetchBytes: (url: string) => Promise<ArrayBuffer> = fetchObjectUrl
): AudioPlayerPort {
  const decoded = new Map<string, Promise<AudioBuffer>>();
  const progressHandlers = new Set<(fraction: number) => void>();
  const endedHandlers = new Set<() => void>();

  // Bumped by every call that changes what should be heard, so a play still
  // decoding or resuming when it is overtaken never starts.
  let token = 0;
  let source: AudioBufferSourceNode | null = null;
  let clip: AudioBuffer | null = null;
  let startedAt = 0;
  let pausedAt: number | null = null;
  let ticker: ReturnType<typeof setInterval> | undefined;

  const decode = (url: string) => {
    let pending = decoded.get(url);
    // Re-inserted on every use, so the Map's insertion order is recency order.
    decoded.delete(url);
    if (pending === undefined) {
      const attempt = fetchBytes(url).then((bytes) => output.context().decodeAudioData(bytes));
      attempt.catch(() => {
        if (decoded.get(url) === attempt) {
          decoded.delete(url);
        }
      });
      pending = attempt;
    }
    decoded.set(url, pending);
    if (decoded.size > DECODED_CLIPS) {
      decoded.delete(decoded.keys().next().value as string);
    }
    return pending;
  };

  const elapsed = (buffer: AudioBuffer) =>
    Math.min(Math.max(output.context().currentTime - startedAt, 0), buffer.duration);

  const silence = () => {
    clearInterval(ticker);
    if (source !== null) {
      // Detached first: a stopped source still fires `ended`, and a clip cut
      // short is not a clip heard to its end.
      source.onended = null;
      source.stop();
      source = null;
    }
    output.setSounding(false);
  };

  const sound = (buffer: AudioBuffer, offset: number) => {
    const context = output.context();
    const node = context.createBufferSource();
    node.buffer = buffer;
    node.connect(context.destination);
    node.onended = () => {
      clearInterval(ticker);
      source = null;
      clip = null;
      output.setSounding(false);
      for (const handler of endedHandlers) {
        handler();
      }
    };

    output.setSounding(true);
    node.start(0, offset);
    source = node;
    startedAt = context.currentTime - offset;
    pausedAt = null;

    ticker = setInterval(() => {
      const fraction = buffer.duration > 0 ? elapsed(buffer) / buffer.duration : 0;
      for (const handler of progressHandlers) {
        handler(fraction);
      }
    }, PROGRESS_INTERVAL_MS);
  };

  const begin = async (era: number, buffer: AudioBuffer, offset: number) => {
    const running = await output.ensureRunning();
    if (era !== token) {
      throw superseded();
    }
    if (!running) {
      throw new Error('Audio output is locked until the next user gesture');
    }
    sound(buffer, offset);
  };

  return {
    play(url) {
      if (PROTECTED_AUDIO.test(url)) {
        return Promise.reject(new Error('Protected audio must be buffered before playback'));
      }

      const era = (token += 1);
      silence();
      clip = null;
      pausedAt = null;

      return decode(url).then((buffer) => {
        if (era !== token) {
          throw superseded();
        }
        clip = buffer;
        return begin(era, buffer, 0);
      });
    },

    pause() {
      token += 1;
      if (source !== null && clip !== null) {
        pausedAt = elapsed(clip);
      }
      silence();
    },

    resume() {
      if (clip === null || pausedAt === null) {
        return Promise.resolve();
      }
      return begin((token += 1), clip, pausedAt);
    },

    stop() {
      token += 1;
      silence();
      clip = null;
      pausedAt = null;
    },

    onProgress(handler) {
      progressHandlers.add(handler);
      return () => progressHandlers.delete(handler);
    },

    onEnded(handler) {
      endedHandlers.add(handler);
      return () => endedHandlers.delete(handler);
    },

    // A decoded buffer cannot fail part way through; every failure surfaces as
    // a rejected play() or resume() instead.
    onError() {
      return () => undefined;
    },
  };
}
