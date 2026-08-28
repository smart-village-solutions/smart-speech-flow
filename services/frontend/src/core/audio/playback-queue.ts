import type { AudioPlayerPort } from './player.port';

export interface PlaybackState {
  /** The message whose audio is playing, or null when nothing is. */
  playingId: string | null;
  /** Progress of the playing clip, 0 to 1. Zero whenever nothing is playing. */
  progress: number;
  /** True while the listener has paused the clip named by `playingId`. */
  paused: boolean;
  /**
   * Clips heard through to the end. Their waveforms stay solid rather than
   * emptying, which is what the export does: on the last bar it stops the
   * animation but keeps the bar count (export 1212).
   */
  completedIds: ReadonlySet<string>;
}

export interface PlaybackQueue {
  getState: () => PlaybackState;
  subscribe: (listener: () => void) => () => void;
  enqueue: (id: string, url: string) => void;
  playNow: (id: string, url: string) => void;
  /** Silence now and drop anything waiting. */
  stop: () => void;
  /**
   * Hold the current clip where it is. Distinct from `hold`, which belongs to
   * the microphone: a pause keeps the clip playing-but-silent so the waveform
   * stays where the listener stopped it, where a hold hands the clip back to
   * the queue to be heard again in full.
   */
  pause: () => void;
  /** Carry on from where `pause` stopped. */
  resume: () => void;
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

type Playing = Omit<PlaybackState, 'completedIds'>;

const IDLE: Playing = { playingId: null, progress: 0, paused: false };

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

  let state: PlaybackState = { ...IDLE, completedIds: new Set<string>() };
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

  // Carried alongside every emit rather than passed in, so no caller has to
  // remember it: the set changes only when a clip finishes or is played again.
  let completedIds: ReadonlySet<string> = new Set<string>();

  const setCompleted = (id: string, completed: boolean) => {
    if (completedIds.has(id) === completed) {
      return;
    }
    const next = new Set(completedIds);
    if (completed) {
      next.add(id);
    } else {
      next.delete(id);
    }
    completedIds = next;
  };

  const emit = (next: Playing) => {
    state = { ...next, completedIds };
    for (const listener of listeners) {
      listener();
    }
  };

  const start = (clip: Clip) => {
    const era = (generation += 1);
    heard.add(clip.id);
    // Playing it again draws the waveform afresh, so it must stop counting as
    // heard in full until it is.
    setCompleted(clip.id, false);
    playing = clip;
    audible = false;
    emit({ playingId: clip.id, progress: 0, paused: false });

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

  const pause = () => {
    if (state.playingId === null || state.paused) {
      return;
    }
    // Pausing a clip whose play() has not settled yet rejects that promise with
    // AbortError, which would otherwise reach start()'s rejection arm and
    // advance past the very clip the listener just paused. Every other path
    // into the player bumps the generation before calling it, for this reason.
    generation += 1;
    player.pause();
    emit({ ...state, paused: true });
  };

  const resume = () => {
    if (!state.paused) {
      return;
    }

    const era = generation;
    emit({ ...state, paused: false });

    player.resume().then(
      // Restores the invariant `pause` broke: the clip's original play() may
      // have been aborted before it resolved, leaving `audible` false, and the
      // error event relies on it to know whether a failure has already been
      // dealt with by a rejection.
      () => {
        if (era === generation) {
          audible = true;
        }
      },
      // A resume can fail the same way a play can — a source that has since
      // gone away. Treat it as the clip being over rather than leaving a button
      // that says pause over silence.
      () => {
        if (era === generation) {
          advance();
        }
      }
    );
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
      const offEnded = player.onEnded(() => {
        // Only a clip that reached its end is solid afterwards. A clip cut
        // short — by the microphone, by a tap on another bubble — is not, and
        // neither path comes through here.
        if (playing !== null) {
          setCompleted(playing.id, true);
        }
        advance();
      });
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

      // A paused clip must not stall the conversation: speech arriving now is
      // worth more than a replay someone stopped half way, so the arrival takes
      // the player rather than waiting behind a pause that may never be lifted.
      if (state.playingId === null || state.paused) {
        if (state.paused) {
          player.stop();
        }
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
    pause,
    resume,
    hold,
    release,
  };
}
