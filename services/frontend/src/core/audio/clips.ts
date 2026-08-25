import { BAR_COUNT } from './waveform';
import { peaksFromSamples } from './levels';

export interface Clip {
  /** Plays from memory, so a repeat costs no network. */
  objectUrl: string;
  /** Bar heights, one per waveform bar. */
  peaks: number[];
}

export interface ClipLoaderDeps {
  fetchBytes: (url: string) => Promise<ArrayBuffer>;
  /** Decoded samples of the first channel. */
  decode: (bytes: ArrayBuffer) => Promise<Float32Array>;
  createObjectUrl: (bytes: ArrayBuffer) => string;
  revokeObjectUrl: (url: string) => void;
  bars?: number;
}

export interface ClipLoader {
  load: (url: string) => Promise<Clip>;
  /** The clip if it is already in memory. Never waits, never fetches. */
  peek: (url: string) => Clip | null;
  dispose: () => void;
}

/**
 * Downloads each clip once and keeps it, so the waveform and the audio element
 * share a single fetch. The gateway serves audio with no cache headers
 * (`routes/session.py:1269`), so without this the browser is free to download
 * the same clip again for every play.
 *
 * A failure is not cached: the waveform falls back to its decorative shape and
 * playback to the network url, and a later attempt is free to try again.
 */
export function createClipLoader(deps: ClipLoaderDeps): ClipLoader {
  const { fetchBytes, decode, createObjectUrl, revokeObjectUrl, bars = BAR_COUNT } = deps;

  const clips = new Map<string, Clip>();
  const inFlight = new Map<string, Promise<Clip>>();

  return {
    async load(url) {
      const held = clips.get(url);
      if (held !== undefined) {
        return held;
      }

      const running = inFlight.get(url);
      if (running !== undefined) {
        return running;
      }

      const attempt = (async () => {
        const bytes = await fetchBytes(url);
        const samples = await decode(bytes);
        const clip: Clip = {
          objectUrl: createObjectUrl(bytes),
          peaks: peaksFromSamples(samples, bars),
        };
        clips.set(url, clip);
        return clip;
      })().finally(() => {
        inFlight.delete(url);
      });

      inFlight.set(url, attempt);
      return attempt;
    },

    peek(url) {
      return clips.get(url) ?? null;
    },

    dispose() {
      for (const clip of clips.values()) {
        revokeObjectUrl(clip.objectUrl);
      }
      clips.clear();
      inFlight.clear();
    },
  };
}

/** The real thing: fetch, decode through Web Audio, keep the bytes as a blob. */
export function createBrowserClipLoader(): ClipLoader {
  let context: AudioContext | null = null;

  const audioContext = (): AudioContext => {
    if (context === null) {
      const browser = globalThis as unknown as {
        AudioContext?: typeof AudioContext;
        webkitAudioContext?: typeof AudioContext;
      };
      const Constructor = browser.AudioContext ?? browser.webkitAudioContext;
      if (!Constructor) {
        throw new Error('Web Audio is unavailable');
      }
      context = new Constructor();
    }
    return context;
  };

  return createClipLoader({
    fetchBytes: async (url) => {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Audio request failed: ${response.status}`);
      }
      return response.arrayBuffer();
    },

    // decodeAudioData detaches the buffer it is given, so it gets a copy —
    // otherwise the bytes would be gone before the blob could be made.
    decode: async (bytes) => {
      const decoded = await audioContext().decodeAudioData(bytes.slice(0));
      return decoded.getChannelData(0);
    },

    createObjectUrl: (bytes) => URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' })),
    revokeObjectUrl: (url) => URL.revokeObjectURL(url),
  });
}
