import type { PlaybackEvent } from '@/domain/recording/recordingSession.types';

export interface PlaybackSnapshot {
  playingId: string | null;
  completedIds: ReadonlySet<string>;
}

export interface PlaybackReport {
  messageId: string;
  event: PlaybackEvent;
}

/**
 * What happened between two playback states: a clip that began, and clips heard
 * to the end. Replaying a clip begins it again, so it is reported again.
 */
export function playbackReports(
  previous: PlaybackSnapshot,
  next: PlaybackSnapshot
): PlaybackReport[] {
  const reports: PlaybackReport[] = [];
  if (next.playingId !== null && next.playingId !== previous.playingId) {
    reports.push({ messageId: next.playingId, event: 'started' });
  }
  for (const messageId of next.completedIds) {
    if (!previous.completedIds.has(messageId)) {
      reports.push({ messageId, event: 'completed' });
    }
  }
  return reports;
}
