import { useCallback, useEffect, useState } from 'react';
import { usePlayback } from '@/app/providers/playback';
import { useServices } from '@/app/providers/services';
import { consentClipId, isConsentClip } from './consentClip';

/**
 * The consent text read aloud through the conversation's own player (spec §6),
 * so the speaker a gesture unlocked plays it. The clip is loaded first: a
 * language without a voice hides the control instead of failing silently.
 */
export function useReadAloud(
  sessionId: string,
  requestId: string | null,
  textSha256: string | null
) {
  const { recordingSession } = useServices();
  const { playingId, playNow, stop, clips } = usePlayback();
  const [failedFor, setFailedFor] = useState<string | null>(null);
  const id = requestId === null ? null : consentClipId(requestId);
  const reading = id !== null && playingId === id;

  // A closed or replaced question stops its reading.
  useEffect(() => {
    if (playingId !== null && isConsentClip(playingId) && playingId !== id) stop();
  }, [id, playingId, stop]);

  const toggle = useCallback(async () => {
    if (requestId === null || id === null || textSha256 === null) return;
    if (reading) {
      stop();
      return;
    }
    const url = recordingSession.consentAudioUrl(sessionId, requestId, textSha256);
    try {
      await clips.load(url);
      playNow(id, url);
    } catch {
      setFailedFor(requestId);
    }
  }, [clips, id, playNow, reading, recordingSession, requestId, sessionId, stop, textSha256]);

  return { available: requestId !== null && failedFor !== requestId, reading, toggle };
}
