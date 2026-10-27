import { useEffect, useRef } from 'react';
import { usePlayback } from '@/app/providers/playback';
import { useServices } from '@/app/providers/services';
import type { ClientRole } from '@/core/roles';
import { playbackReports, type PlaybackSnapshot } from './playbackReports';

/**
 * Reports each clip this screen plays while its band shows recording live
 * (spec §7.1): "played" is not "heard", so the archive keeps what the screen
 * saw. The gateway decides whether a report is archived; a failed report is
 * not worth an error on screen.
 */
export function usePlaybackReports(sessionId: string, role: ClientRole, live: boolean): void {
  const { recordingSession } = useServices();
  const { playingId, completedIds } = usePlayback();
  const previous = useRef<PlaybackSnapshot>({ playingId: null, completedIds: new Set() });
  // One report at a time, so a clip's completion never reaches the gateway before its start.
  const queue = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    const next = { playingId, completedIds };
    const reports = playbackReports(previous.current, next);
    previous.current = next;
    if (!live) {
      return;
    }
    for (const { messageId, event } of reports) {
      queue.current = queue.current.then(() =>
        recordingSession.reportPlayback(sessionId, role, messageId, event).catch(() => undefined)
      );
    }
  }, [completedIds, live, playingId, recordingSession, role, sessionId]);
}
