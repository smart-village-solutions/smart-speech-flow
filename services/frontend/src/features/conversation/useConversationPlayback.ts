import { useEffect } from 'react';

interface PlaybackControls {
  hold: () => void;
  release: () => void;
  stop: () => void;
}

/**
 * When the conversation's audio may sound. Nothing is spoken aloud into an open
 * microphone: arrivals queue instead, and whatever was playing is replayed in
 * full once the mic closes. Leaving the screen silences it outright, since the
 * player outlives the screen.
 */
export function useConversationPlayback(recording: boolean, playback: PlaybackControls): void {
  const { hold, release, stop } = playback;

  useEffect(() => {
    if (!recording) {
      return;
    }

    hold();
    return release;
  }, [recording, hold, release]);

  useEffect(() => stop, [stop]);
}
