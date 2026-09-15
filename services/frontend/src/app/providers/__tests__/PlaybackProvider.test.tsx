import { StrictMode } from 'react';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { PlaybackProvider } from '@/app/providers/PlaybackProvider';
import { usePlayback } from '@/app/providers/playback';
import { createFakeAudioPlayer } from '@/test/fakeAudioPlayer';
import type { ClipLoader } from '@/core/audio/clips';

function Probe() {
  const { playingId, progress, paused, enqueue, playNow, pause, resume, hold, release } =
    usePlayback();

  return (
    <div>
      <span data-testid="playing">{playingId ?? 'none'}</span>
      <span data-testid="progress">{progress}</span>
      <span data-testid="paused">{paused ? 'yes' : 'no'}</span>
      <button type="button" onClick={() => enqueue('a', '/a.wav')}>
        enqueue a
      </button>
      <button type="button" onClick={() => enqueue('b', '/b.wav')}>
        enqueue b
      </button>
      <button type="button" onClick={() => playNow('a', '/a.wav')}>
        play a
      </button>
      <button type="button" onClick={() => playNow('c', '/c.wav')}>
        play c
      </button>
      <button type="button" onClick={pause}>
        pause
      </button>
      <button type="button" onClick={resume}>
        resume
      </button>
      <button type="button" onClick={hold}>
        hold
      </button>
      <button type="button" onClick={release}>
        release
      </button>
    </div>
  );
}

function passthroughClips(): ClipLoader {
  return {
    load: vi.fn(async (url: string) => ({ objectUrl: url, peaks: [] })),
    peek: vi.fn().mockReturnValue(null),
    dispose: vi.fn(),
  };
}

function setup(children: ReactNode = <Probe />, clips?: ClipLoader) {
  const player = createFakeAudioPlayer();
  render(
    <PlaybackProvider player={player.port} clips={clips ?? passthroughClips()}>
      {children}
    </PlaybackProvider>
  );
  return player;
}

const click = (name: string) => userEvent.click(screen.getByRole('button', { name }));
const playing = () => screen.getByTestId('playing').textContent;
const paused = () => screen.getByTestId('paused').textContent;

describe('PlaybackProvider', () => {
  it('authenticates and buffers a protected clip before giving it to the player', async () => {
    const clips: ClipLoader = {
      load: vi.fn().mockResolvedValue({ objectUrl: 'blob:authenticated', peaks: [] }),
      peek: vi.fn().mockReturnValue(null),
      dispose: vi.fn(),
    };
    const player = setup(<Probe />, clips);

    await click('enqueue a');
    await vi.waitFor(() => expect(clips.load).toHaveBeenCalledWith('/a.wav'));
    await vi.waitFor(() => expect(player.played).toEqual(['blob:authenticated']));

    expect(player.played).not.toContain('/a.wav');
  });

  it('does not fall back to an unauthenticated media-element request', async () => {
    const clips: ClipLoader = {
      load: vi.fn().mockRejectedValue(new Error('unauthorized')),
      peek: vi.fn().mockReturnValue(null),
      dispose: vi.fn(),
    };
    const player = setup(<Probe />, clips);

    await click('enqueue a');
    await vi.waitFor(() => expect(clips.load).toHaveBeenCalledWith('/a.wav'));

    expect(player.played).toEqual([]);
  });

  it('plays an enqueued clip straight away when idle', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();

    expect(player.played).toEqual(['/a.wav']);
    expect(playing()).toBe('a');
  });

  it('queues a second arrival and plays it in order when the first ends', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await click('enqueue b');

    expect(player.played).toEqual(['/a.wav']);
    expect(playing()).toBe('a');

    await player.end();

    expect(player.played).toEqual(['/a.wav', '/b.wav']);
    expect(playing()).toBe('b');
  });

  it('goes idle once the queue drains', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await player.end();

    expect(playing()).toBe('none');
    expect(screen.getByTestId('progress').textContent).toBe('0');
  });

  it('ignores an id that is already playing or queued', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await click('enqueue a');
    await click('enqueue b');
    await click('enqueue b');
    await player.end();

    expect(player.played).toEqual(['/a.wav', '/b.wav']);
  });

  it('never replays an id that has already been heard', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await player.end();
    await click('enqueue a');

    expect(player.played).toEqual(['/a.wav']);
    expect(playing()).toBe('none');
  });

  it('restarts the clip that is already playing when it is tapped', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await player.progress(0.5);
    await click('play a');
    await player.started();

    expect(player.played).toEqual(['/a.wav', '/a.wav']);
    expect(playing()).toBe('a');
    expect(screen.getByTestId('progress').textContent).toBe('0');
  });

  it('interrupts for a tap on another bubble and keeps the queue for afterwards', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await click('enqueue b');
    await click('play c');
    await player.started();

    expect(playing()).toBe('c');
    expect(player.stop).toHaveBeenCalled();

    await player.end();

    expect(playing()).toBe('b');
    expect(player.played).toEqual(['/a.wav', '/c.wav', '/b.wav']);
  });

  it('tracks progress only for the clip that is playing', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await player.progress(0.4);

    expect(screen.getByTestId('progress').textContent).toBe('0.4');
  });

  it('moves on to the next clip when the browser refuses to autoplay', async () => {
    const player = setup();

    await click('enqueue a');
    await click('enqueue b');
    await player.rejected();

    expect(playing()).toBe('b');
    expect(player.played).toEqual(['/a.wav', '/b.wav']);
  });

  it('goes idle when the only clip is refused', async () => {
    const player = setup();

    await click('enqueue a');
    await player.rejected();

    expect(playing()).toBe('none');
  });

  it('skips a clip that fails to load and plays the next', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await click('enqueue b');
    await player.fail();

    expect(playing()).toBe('b');
    expect(player.played).toEqual(['/a.wav', '/b.wav']);
  });

  // A bad source both rejects play() and fires the element's error event. They
  // describe one failure, so only the first may move the queue on — otherwise
  // the clip behind it is skipped without ever being heard.
  it('advances once when a clip both refuses and errors', async () => {
    const player = setup();

    await click('enqueue a');
    await click('enqueue b');
    await player.rejected();
    await player.fail();

    expect(playing()).toBe('b');
    expect(player.played).toEqual(['/a.wav', '/b.wav']);
  });

  it('keeps working through the StrictMode double mount', async () => {
    const player = createFakeAudioPlayer();
    render(
      <StrictMode>
        <PlaybackProvider player={player.port} clips={passthroughClips()}>
          <Probe />
        </PlaybackProvider>
      </StrictMode>
    );

    await click('enqueue a');
    await player.started();
    await click('enqueue b');
    await player.end();

    // A torn-down listener would leave 'a' playing for ever.
    expect(playing()).toBe('b');
  });

  it('holds an arrival back while the microphone is open', async () => {
    const player = setup();

    await click('hold');
    await click('enqueue a');

    expect(player.played).toEqual([]);
    expect(playing()).toBe('none');
  });

  it('plays what queued up once the microphone closes, in order', async () => {
    const player = setup();

    await click('hold');
    await click('enqueue a');
    await click('enqueue b');
    await click('release');
    await player.started();

    expect(playing()).toBe('a');

    await player.end();

    expect(player.played).toEqual(['/a.wav', '/b.wav']);
  });

  it('silences the clip playing when a hold starts and replays it afterwards', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await player.progress(0.5);
    await click('hold');

    expect(player.stop).toHaveBeenCalled();
    expect(playing()).toBe('none');

    await click('release');
    await player.started();

    expect(playing()).toBe('a');
    expect(player.played).toEqual(['/a.wav', '/a.wav']);
  });

  it('defers a tapped clip until the hold is released', async () => {
    const player = setup();

    await click('hold');
    await click('play c');

    expect(player.played).toEqual([]);

    await click('release');

    expect(player.played).toEqual(['/c.wav']);
  });

  it('stays idle when released with nothing waiting', async () => {
    const player = setup();

    await click('hold');
    await click('release');

    expect(player.played).toEqual([]);
    expect(playing()).toBe('none');
  });

  it('ignores a repeated hold', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await click('hold');
    await click('hold');
    await click('release');
    await player.started();

    // One re-queue, not two.
    expect(player.played).toEqual(['/a.wav', '/a.wav']);
    expect(playing()).toBe('a');
  });

  it('stops playback when the provider unmounts', async () => {
    const player = createFakeAudioPlayer();
    const view = render(
      <PlaybackProvider player={player.port} clips={passthroughClips()}>
        <Probe />
      </PlaybackProvider>
    );

    await click('enqueue a');
    await player.started();
    view.unmount();

    expect(player.stop).toHaveBeenCalled();
  });
});

describe('usePlayback', () => {
  it('refuses to work outside a provider', () => {
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(() => render(<Probe />)).toThrow('usePlayback must be used inside a PlaybackProvider');

    quiet.mockRestore();
  });

  it('holds the clip and its progress across a pause, then carries on', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await player.progress(0.4);

    await click('pause');
    expect(player.paused).toHaveBeenCalledTimes(1);
    expect(paused()).toBe('yes');
    // Still the playing clip: pausing is not stopping, and the waveform must
    // stay where the listener left it rather than emptying.
    expect(playing()).toBe('a');
    expect(screen.getByTestId('progress').textContent).toBe('0.4');

    await click('resume');
    expect(player.resumed).toHaveBeenCalledTimes(1);
    expect(paused()).toBe('no');
    // A resume reuses the loaded clip; it is not a second play().
    expect(player.played).toEqual(['/a.wav']);
  });

  it('ignores a resume when nothing was paused, and a pause when nothing plays', async () => {
    const player = setup();

    await click('resume');
    await click('pause');

    expect(player.resumed).not.toHaveBeenCalled();
    expect(player.paused).not.toHaveBeenCalled();
  });

  // Every other test here pauses a clip that is already audible. Pausing inside
  // the load window is the case that regressed: a real element rejects the
  // pending play() with AbortError, and the queue used to read that as the clip
  // being over and advance past it, emptying the waveform of the clip the
  // listener had just paused.
  it('keeps a clip paused when pausing aborts its pending play', async () => {
    const player = setup();

    await click('enqueue a');
    await click('pause');
    await player.rejected('AbortError');

    expect(playing()).toBe('a');
    expect(paused()).toBe('yes');
  });

  it('plays the authenticated clip after pausing while its download is pending', async () => {
    let finishDownload!: (clip: { objectUrl: string; peaks: number[] }) => void;
    const clips: ClipLoader = {
      load: vi.fn(
        () =>
          new Promise((resolve) => {
            finishDownload = resolve;
          })
      ),
      peek: vi.fn().mockReturnValue(null),
      dispose: vi.fn(),
    };
    const player = setup(<Probe />, clips);

    await click('enqueue a');
    await vi.waitFor(() => expect(clips.load).toHaveBeenCalledWith('/a.wav'));
    await click('pause');

    await act(async () => {
      finishDownload({ objectUrl: 'blob:authenticated-a', peaks: [] });
    });
    expect(player.played).toEqual([]);

    await click('resume');
    await vi.waitFor(() => expect(player.played).toEqual(['blob:authenticated-a']));

    expect(player.resumed).not.toHaveBeenCalled();
    expect(playing()).toBe('a');
    expect(paused()).toBe('no');
  });

  // A pause must not stall the conversation. The clip someone stopped half way
  // is worth less than speech arriving now, so an arrival takes the player.
  it('lets a new arrival take over from a paused clip', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await click('pause');

    await click('enqueue b');
    await player.started();

    expect(player.played).toEqual(['/a.wav', '/b.wav']);
    expect(playing()).toBe('b');
    expect(paused()).toBe('no');
  });

  it('drops the pause when the conversation stops', async () => {
    const player = setup();

    await click('enqueue a');
    await player.started();
    await click('pause');
    await click('hold');

    expect(playing()).toBe('none');
    expect(paused()).toBe('no');
  });
});
