/**
 * The conversation's one route to the speaker: a single AudioContext, shared by
 * the clip loader for decoding and the player for output.
 *
 * It exists because browsers only let sound start inside a user gesture, and
 * iOS Safari applies that to every `<audio>` play, so an arriving message could
 * never autoplay through a media element there. An AudioContext resumed once
 * inside a gesture stays running, and from then on any clip can start without
 * one — in Safari, Chrome and Firefox alike.
 */
export interface AudioOutput {
  /** Created on first use. Throws where the browser has no Web Audio. */
  context: () => AudioContext;
  /** Call from inside a user gesture; a no-op once the context is running. */
  unlock: () => void;
  /** Whether sound can start now. Never waits on a resume the browser withholds. */
  ensureRunning: () => Promise<boolean>;
  /** Mark speech as sounding, so the iOS silent switch does not mute it. */
  setSounding: (sounding: boolean) => void;
}

export interface AudioOutputDeps {
  createContext: () => AudioContext | null;
  /** `navigator.audioSession`, where the browser has one (Safari 17 and later). */
  session: { type: string } | null;
  resumeTimeoutMs?: number;
}

// Compared through a function: TypeScript narrows `state` after one check and
// then rejects the same comparison after an await as impossible.
const isRunning = (context: AudioContext) => context.state === 'running';

export function createAudioOutput(deps: AudioOutputDeps = browserAudioOutputDeps()): AudioOutput {
  const { createContext, session, resumeTimeoutMs = 1000 } = deps;
  let created: AudioContext | null = null;
  // Set when a resume times out, cleared by the next gesture: until then the
  // answer is already known, and waiting again would only delay the queue.
  let refused = false;

  const context = () => {
    if (created === null) {
      created = createContext();
      if (created === null) {
        throw new Error('Web Audio is unavailable');
      }
    }
    return created;
  };

  const available = (): AudioContext | null => {
    try {
      return context();
    } catch {
      return null;
    }
  };

  return {
    context,

    unlock() {
      refused = false;
      const audio = available();
      if (audio === null || isRunning(audio)) {
        return;
      }
      void audio.resume().catch(() => undefined);
      // Older WebKit unlocks only on a sound started inside the gesture itself;
      // the resume alone is not enough there.
      const silence = audio.createBufferSource();
      silence.buffer = audio.createBuffer(1, 1, audio.sampleRate);
      silence.connect(audio.destination);
      silence.start(0);
    },

    async ensureRunning() {
      const audio = available();
      if (audio === null) {
        return false;
      }
      if (isRunning(audio)) {
        return true;
      }
      if (refused) {
        return false;
      }

      // Without a gesture iOS leaves the resume pending indefinitely, which
      // would leave the queue showing pause over silence.
      let timer: ReturnType<typeof setTimeout> | undefined;
      const timeout = new Promise<void>((resolve) => {
        timer = setTimeout(resolve, resumeTimeoutMs);
      });
      await Promise.race([audio.resume().catch(() => undefined), timeout]);
      clearTimeout(timer);

      refused = !isRunning(audio);
      return !refused;
    },

    setSounding(sounding) {
      // Held only while speech plays, and handed back to 'auto' otherwise: a
      // 'playback' session left in place when the microphone opens could stop
      // WebKit choosing play-and-record.
      if (session !== null) {
        session.type = sounding ? 'playback' : 'auto';
      }
    },
  };
}

function browserAudioOutputDeps(): AudioOutputDeps {
  const browser = globalThis as unknown as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
    navigator?: { audioSession?: { type: string } };
  };

  return {
    createContext: () => {
      const Constructor = browser.AudioContext ?? browser.webkitAudioContext;
      return Constructor ? new Constructor() : null;
    },
    session: browser.navigator?.audioSession ?? null,
  };
}
