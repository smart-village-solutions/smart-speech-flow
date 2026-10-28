import { act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { usePlayback } from '@/app/providers/playback';
import type { RecordingSessionRepository } from '@/domain/recording/recordingSession.repository';
import { createFakeAudioPlayer } from '@/test/fakeAudioPlayer';
import { renderWithProviders } from '@/test/renderWithProviders';
import { consentClipId } from '../consentClip';
import { playbackReports } from '../playbackReports';
import { usePlaybackReports } from '../usePlaybackReports';

const none = new Set<string>();

describe('playbackReports', () => {
  it('reports a clip that begins, once', () => {
    expect(
      playbackReports(
        { playingId: null, completedIds: none },
        { playingId: 'm1', completedIds: none }
      )
    ).toEqual([{ messageId: 'm1', event: 'started' }]);
    expect(
      playbackReports(
        { playingId: 'm1', completedIds: none },
        { playingId: 'm1', completedIds: none }
      )
    ).toEqual([]);
  });

  it('reports each clip newly heard to the end', () => {
    expect(
      playbackReports(
        { playingId: 'm1', completedIds: new Set(['m0']) },
        { playingId: null, completedIds: new Set(['m0', 'm1']) }
      )
    ).toEqual([{ messageId: 'm1', event: 'completed' }]);
  });

  it('reports a replay as a new start', () => {
    expect(
      playbackReports(
        { playingId: null, completedIds: new Set(['m1']) },
        { playingId: 'm1', completedIds: none }
      )
    ).toEqual([{ messageId: 'm1', event: 'started' }]);
  });
});

interface ReporterProps {
  live: boolean;
  clip: string;
  onReady: (play: () => void) => void;
}

function Reporter({ live, clip, onReady }: ReporterProps) {
  const { enqueue } = usePlayback();
  usePlaybackReports('A1B2C3D4', 'admin', live);
  onReady(() => enqueue(clip, `/audio/${clip}`));
  return null;
}

async function playToEnd(
  live: boolean,
  reportPlayback: ReturnType<typeof vi.fn> = vi.fn().mockResolvedValue(undefined),
  clip = 'm1'
) {
  const player = createFakeAudioPlayer();
  let play = () => {};
  renderWithProviders(<Reporter live={live} clip={clip} onReady={(start) => (play = start)} />, {
    player: player.port,
    services: { recordingSession: { reportPlayback } as unknown as RecordingSessionRepository },
  });
  await act(async () => {
    play();
  });
  await player.started();
  await player.end();
  return reportPlayback;
}

describe('usePlaybackReports', () => {
  it('reports start and completion while recording is live', async () => {
    const reportPlayback = await playToEnd(true);

    expect(reportPlayback.mock.calls).toEqual([
      ['A1B2C3D4', 'admin', 'm1', 'started'],
      ['A1B2C3D4', 'admin', 'm1', 'completed'],
    ]);
  });

  it('never reports the consent text read aloud: it is no message', async () => {
    const reportPlayback = await playToEnd(true, undefined, consentClipId('r-1'));

    expect(reportPlayback).not.toHaveBeenCalled();
  });

  it('reports nothing while recording is not live', async () => {
    const reportPlayback = await playToEnd(false);

    expect(reportPlayback).not.toHaveBeenCalled();
  });

  it('sends a completion only after its start has been answered', async () => {
    const answers: (() => void)[] = [];
    const reportPlayback = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          answers.push(resolve);
        })
    );

    await playToEnd(true, reportPlayback);
    expect(reportPlayback.mock.calls.map((call) => call[3])).toEqual(['started']);

    await act(async () => {
      answers[0]();
    });
    expect(reportPlayback.mock.calls.map((call) => call[3])).toEqual(['started', 'completed']);
  });
});
