import { useEffect, useMemo, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import type { AudioPlayerPort } from '@/core/audio/player.port';
import type { AudioOutput } from '@/core/audio/audio-output';
import type { ClipLoader } from '@/core/audio/clips';
import { createPlaybackQueue } from '@/core/audio/playback-queue';
import { createWebAudioPlayer } from '@/core/audio/web-audio-player';
import { PlaybackContext } from './playback';

interface PlaybackProviderProps {
  children: ReactNode;
  /** Injected by tests; the default plays through `output`. */
  player?: AudioPlayerPort;
  /** The shared AudioContext, unlocked by any gesture while this is mounted. */
  output: AudioOutput;
  /** Authenticated clip loader from the application composition root. */
  clips: ClipLoader;
}

// The events browsers count as user activation. Listened for in the capture
// phase so the speaker is unlocked before a tapped control asks it to play.
const GESTURES = ['click', 'touchend', 'keydown'] as const;

/** Owns the conversation's single audio player; see `createPlaybackQueue`. */
export function PlaybackProvider({
  children,
  player,
  output,
  clips,
}: Readonly<PlaybackProviderProps>) {
  const loader = clips;

  const queue = useMemo(
    () =>
      createPlaybackQueue(
        player ?? createWebAudioPlayer(output),
        async (url) => (await loader.load(url)).objectUrl
      ),
    [loader, output, player]
  );

  useEffect(() => queue.connect(), [queue]);

  // Every gesture, not just the first: iOS interrupts a running context when
  // the page is backgrounded or a call comes in, and only a gesture restarts it.
  useEffect(() => {
    const unlock = () => output.unlock();
    const retry = (event: Event) => {
      // Enter/Space can activate a button with a later click. Likewise,
      // touchend unlocks the output, but its following click owns the retry.
      if (event instanceof KeyboardEvent && (event.key === 'Enter' || event.key === ' ')) {
        return;
      }
      queue.retryBlocked();
    };
    for (const type of GESTURES) {
      document.addEventListener(type, unlock, { capture: true });
    }
    // Bubble phase: React's control handlers at the app root must run first.
    // A microtask in capture can run before those handlers for trusted events.
    document.addEventListener('click', retry);
    document.addEventListener('keydown', retry);
    return () => {
      for (const type of GESTURES) {
        document.removeEventListener(type, unlock, { capture: true });
      }
      document.removeEventListener('click', retry);
      document.removeEventListener('keydown', retry);
    };
  }, [output, queue]);

  useEffect(() => () => loader.dispose(), [loader]);

  const state = useSyncExternalStore(queue.subscribe, queue.getState);

  const value = useMemo(
    () => ({
      ...state,
      enqueue: queue.enqueue,
      playNow: queue.playNow,
      stop: queue.stop,
      pause: queue.pause,
      resume: queue.resume,
      hold: queue.hold,
      release: queue.release,
      clips: loader,
    }),
    [state, queue, loader]
  );

  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
}
