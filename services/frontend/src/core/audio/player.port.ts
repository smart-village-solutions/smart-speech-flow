/**
 * One-clip-at-a-time playback, behind a port so the queue can be tested without
 * a real media element — jsdom implements neither `play()` nor timing.
 */
export interface AudioPlayerPort {
  /** Always starts from the beginning, including for the clip already loaded. */
  play(url: string): Promise<void>;
  /** Holds the playhead where it is, so `resume` carries on from there. */
  pause(): void;
  resume(): Promise<void>;
  stop(): void;
  /** Each returns an unsubscribe function. */
  onProgress(handler: (fraction: number) => void): () => void;
  onEnded(handler: () => void): () => void;
  onError(handler: () => void): () => void;
}

export function createDomAudioPlayer(element: HTMLAudioElement): AudioPlayerPort {
  // Tracked here rather than read back from `element.src`, which reflects an
  // absolute URL and so never compares equal to the relative one we set. A
  // needless reassignment would re-download the clip on every repeat.
  let loaded: string | null = null;

  const subscribe = (type: string, handler: EventListener) => {
    element.addEventListener(type, handler);
    return () => element.removeEventListener(type, handler);
  };

  // A failed clip is reloaded rather than replayed from a dead element. This
  // holds whether or not anyone subscribed to onError.
  element.addEventListener('error', () => {
    loaded = null;
  });

  return {
    play(url) {
      if (loaded !== url) {
        element.src = url;
        loaded = url;
      }
      element.currentTime = 0;
      return element.play();
    },

    pause() {
      element.pause();
    },

    // Deliberately not `play(loaded)`: that would rewind. The element keeps its
    // position across a pause, so playing it again continues from there.
    resume() {
      return element.play();
    },

    stop() {
      element.pause();
      element.currentTime = 0;
    },

    onProgress(handler) {
      return subscribe('timeupdate', () => {
        const { currentTime, duration } = element;
        if (Number.isFinite(duration) && duration > 0) {
          handler(currentTime / duration);
        }
      });
    },

    onEnded(handler) {
      return subscribe('ended', () => handler());
    },

    onError(handler) {
      return subscribe('error', () => handler());
    },
  };
}
