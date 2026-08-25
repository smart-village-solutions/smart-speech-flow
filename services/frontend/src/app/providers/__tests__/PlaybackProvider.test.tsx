import { StrictMode } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { PlaybackProvider } from '@/app/providers/PlaybackProvider';
import { usePlayback } from '@/app/providers/playback';
import { createFakeAudioPlayer } from '@/test/fakeAudioPlayer';

function Probe() {
  const { playingId, progress, enqueue, playNow, hold, release } = usePlayback();

  return (
    <div>
      <span data-testid="playing">{playingId ?? 'none'}</span>
      <span data-testid="progress">{progress}</span>
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
      <button type="button" onClick={hold}>
        hold
      </button>
      <button type="button" onClick={release}>
        release
      </button>
    </div>
  );
}

function setup(children: ReactNode = <Probe />) {
  const player = createFakeAudioPlayer();
  render(<PlaybackProvider player={player.port}>{children}</PlaybackProvider>);
  return player;
}

const click = (name: string) => userEvent.click(screen.getByRole('button', { name }));
const playing = () => screen.getByTestId('playing').textContent;

describe('PlaybackProvider', () => {
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
        <PlaybackProvider player={player.port}>
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
      <PlaybackProvider player={player.port}>
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
});