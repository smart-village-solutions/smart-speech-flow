import { createContext, useContext, useEffect, useState } from 'react';
import type { ClipLoader } from '@/core/audio/clips';
import { WAVE_HEIGHTS } from '@/core/audio/waveform';

export interface PlaybackContextValue {
  /** The message whose audio is playing, or null when nothing is. */
  playingId: string | null;
  /** Progress of the playing clip, 0 to 1. Zero whenever nothing is playing. */
  progress: number;
  /** Autoplay an arriving message; waits its turn if something is playing. */
  enqueue: (id: string, url: string) => void;
  /** Play now, from the beginning, interrupting whatever is playing. */
  playNow: (id: string, url: string) => void;
  /** Silence now and drop anything waiting — used on leaving the conversation. */
  stop: () => void;
  /** Suspend playback while the microphone is open; arrivals still queue. */
  hold: () => void;
  /** Resume after a hold. */
  release: () => void;
  /** Downloads and decodes a clip once, for its waveform and its playback. */
  clips: ClipLoader;
}

export const PlaybackContext = createContext<PlaybackContextValue | null>(null);

export function usePlayback(): PlaybackContextValue {
  const value = useContext(PlaybackContext);

  if (value === null) {
    throw new Error('usePlayback must be used inside a PlaybackProvider');
  }

  return value;
}

/**
 * The real shape of a clip, once it has been fetched and decoded. Falls back to
 * the design's decorative shape until then, and for good if Web Audio is
 * unavailable or the clip cannot be decoded.
 */
export function useClipPeaks(url: string | null): number[] {
  const { clips } = usePlayback();
  // The url is kept beside the peaks so a change to it falls back to the
  // decorative shape by derivation, rather than by resetting state in an effect.
  const [loaded, setLoaded] = useState<{ url: string; peaks: number[] } | null>(null);

  useEffect(() => {
    if (url === null) {
      return;
    }

    let cancelled = false;
    void clips
      .load(url)
      .then((clip) => {
        if (!cancelled) {
          setLoaded({ url, peaks: clip.peaks });
        }
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [clips, url]);

  return loaded !== null && loaded.url === url ? loaded.peaks : WAVE_HEIGHTS;
}
