import { useEffect, useMemo, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { createDomAudioPlayer, type AudioPlayerPort } from '@/core/audio/player.port';
import type { ClipLoader } from '@/core/audio/clips';
import { createPlaybackQueue } from '@/core/audio/playback-queue';
import { PlaybackContext } from './playback';

interface PlaybackProviderProps {
  children: ReactNode;
  /** Injected by tests; the default drives a real media element. */
  player?: AudioPlayerPort;
  /** Authenticated clip loader from the application composition root. */
  clips: ClipLoader;
}

/** Owns the conversation's single audio player; see `createPlaybackQueue`. */
export function PlaybackProvider({ children, player, clips }: Readonly<PlaybackProviderProps>) {
  const loader = clips;

  const queue = useMemo(
    () =>
      createPlaybackQueue(
        player ?? createDomAudioPlayer(new Audio()),
        async (url) => (await loader.load(url)).objectUrl
      ),
    [loader, player]
  );

  useEffect(() => queue.connect(), [queue]);

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
