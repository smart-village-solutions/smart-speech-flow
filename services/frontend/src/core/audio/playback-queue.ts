import type { AudioPlayerPort } from './player.port';

export interface PlaybackState {
  /** The message whose audio is playing, or null when nothing is. */
  playingId: string | null;
  /** Progress of the playing clip, 0 to 1. Zero whenever nothing is playing. */
  progress: number;
}

export interface PlaybackQueue {
  getState: () => PlaybackState;
  subscribe: (listener: () => void) => () => void;
  enqueue: (id: string, url: string) => void;
  playNow: (id: string, url: string) => void;
  /** Silence now and drop anything waiting. */
  stop: () => void;
  /**
   * Suspend playback while the microphone is open, so synthesised speech is
   * not recorded back. Arrivals still queue; the clip playing is silenced and
   * put back at the front to be heard in full afterwards.
   */
  hold: () => void;
  /** Resume after a hold, starting whatever queued up meanwhile. */
  release: () => void;
  /**
   * Attaches the player's listeners and returns the detach function. Kept apart
   * from construction so mounting twice — as StrictMode does — attaches twice
   * rather than leaving the queue deaf after the first cleanup.
   */
  connect: () => () => void;
}

interface Clip {
  id: string;
  url: string;
}

const IDLE: PlaybackState = { playingId: null, progress: 0 };

/**
 * One clip at a time, for the whole conversation.
 *
 * Incoming messages autoplay by queueing, so a burst of arrivals is heard in
 * order rather than on top of each other. A tap goes to the front: it stops
 * whatever is playing and starts from the beginning, and the queue picks up
 * afterwards so nothing unheard is lost.
 *
 * Deliberately outside React — it is a queue, not UI, and the mutual recursion
 * between starting a clip and advancing past a failed one reads badly through
 * hooks.
 */
export function createPlaybackQueue(
  player: AudioPlayerPort,
  /** Lets a clip already held in memory be played instead of refetched. */
  resolveUrl: (url: string) => string = (url) => url
): PlaybackQueue {
  const listeners = new Set<() => void>();
  const queue: Clip[] = [];
  const heard = new Set<string>();

  let state: PlaybackState = IDLE;
  let playing: Clip | null = null;
  let held = false;
  // Guards the async gap in play(): a clip interrupted while its promise is
  // still pending must not drive the queue when that promise settles.
  let generation = 0;
  // True once play() has resolved, i.e. the clip is genuinely audible. A source
  // that fails to load both rejects play() and fires the player's error event;
  // the rejection handles it, and the event must not advance the queue a second
  // time and skip whatever was waiting behind it.
  let audible = false;

  const emit = (next: PlaybackState) => {
    state = next;
    for (const listener of listeners) {
      listener();
    }
  };

  const start = (clip: Clip) => {
    const era = (generation += 1);
    heard.add(clip.id);
    playing = clip;
    audible = false;
    emit({ playingId: clip.id, progress: 0 });

    player.play(resolveUrl(clip.url)).then(
      () => {
        if (era === generation) {
          audible = true;
        }
      },
      () => {
        // A rejected play is the browser refusing autoplay, or a bad source.
        // Either way this clip is done; carry on with the queue.
        if (era === generation) {
          advance();
        }
      }
    );
  };

  function advance() {
    const next = held ? undefined : queue.shift();
    if (next === undefined) {
      generation += 1;
      playing = null;
      audible = false;
      emit(IDLE);
      return;
    }
    start(next);
  }

  const stop = () => {
    generation += 1;
    queue.length = 0;
    playing = null;
    audible = false;
    held = false;
    player.stop();
    emit(IDLE);
  };

  const hold = () => {
    if (held) {
      return;
    }
    held = true;

    const interrupted = playing;
    generation += 1;
    playing = null;
    audible = false;
    player.stop();

    if (interrupted !== null) {
      // Back to the front, to be heard in full once the microphone closes.
      queue.unshift(interrupted);
    }

    emit(IDLE);
  };

  const release = () => {
    if (!held) {
      return;
    }
    held = false;

    if (state.playingId === null) {
      advance();
    }
  };

  return {
    getState: () => state,

    connect() {
      const offEnded = player.onEnded(advance);
      // Only a clip that actually started playing can fail this way; a source
      // that never loaded has already been dealt with by play()'s rejection.
      const offError = player.onError(() => {
        if (audible) {
          advance();
        }
      });
      const offProgress = player.onProgress((progress) => {
        if (state.playingId !== null) {
          emit({ ...state, progress });
        }
      });

      return () => {
        offEnded();
        offError();
        offProgress();
        stop();
      };
    },

    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },

    enqueue(id, url) {
      if (heard.has(id) || queue.some((clip) => clip.id === id)) {
        return;
      }

      if (held) {
        queue.push({ id, url });
        return;
      }

      if (state.playingId === null) {
        start({ id, url });
        return;
      }

      queue.push({ id, url });
    },

    playNow(id, url) {
      const queued = queue.findIndex((clip) => clip.id === id);
      if (queued !== -1) {
        queue.splice(queued, 1);
      }

      // A tap during recording is honoured, just not out loud yet.
      if (held) {
        queue.unshift({ id, url });
        return;
      }

      player.stop();
      start({ id, url });
    },

    stop,
    hold,
    release,
  };
}
