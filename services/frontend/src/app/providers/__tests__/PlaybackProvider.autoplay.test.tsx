import type { ReactNode } from 'react';
import { act, fireEvent, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PlaybackProvider } from '@/app/providers/PlaybackProvider';
import { usePlayback } from '@/app/providers/playback';
import { createAudioOutput } from '@/core/audio/audio-output';
import { createWebAudioPlayer } from '@/core/audio/web-audio-player';
import { asAudioContext, createFakeAudioContext } from '@/test/fakeAudioContext';

afterEach(() => vi.useRealTimers());

function setup() {
  vi.useFakeTimers();
  const context = createFakeAudioContext();
  context.resumeBehaviour = 'hang';
  const output = createAudioOutput({
    createContext: () => asAudioContext(context),
    session: null,
  });
  const player = createWebAudioPlayer(output, async () => new ArrayBuffer(8));
  const clips = {
    load: async (url: string) => ({ objectUrl: url, peaks: [] }),
    peek: () => null,
    dispose: () => undefined,
  };
  const view = renderHook(() => usePlayback(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <PlaybackProvider output={output} player={player} clips={clips}>
        {children}
      </PlaybackProvider>
    ),
  });
  const speech = () => context.started.filter((source) => source.buffer?.duration === 10);
  const unlock = async () => {
    context.resumeBehaviour = 'run';
    await act(async () => {
      fireEvent.click(document.body);
    });
  };
  return { ...view, context, speech, unlock };
}

describe('PlaybackProvider blocked autoplay', () => {
  it('plays the first blocked arrival after an ordinary gesture without tapping Play', async () => {
    const { result, speech, unlock } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(speech()).toHaveLength(0);
    expect(result.current.playingId).toBeNull();

    await unlock();

    expect(speech()).toHaveLength(1);
    expect(result.current.playingId).toBe('first');
  });

  it('keeps later arrivals behind the blocked first sentence', async () => {
    const { result, context, speech, unlock } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
      result.current.enqueue('second', 'blob:second');
    });

    await unlock();
    expect(result.current.playingId).toBe('first');
    await act(async () => {
      context.last()?.finish();
    });
    expect(result.current.playingId).toBe('second');
    expect(speech()).toHaveLength(2);
  });

  it('does not replay a blocked sentence after leaving the conversation', async () => {
    const { result, speech, unlock } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
      result.current.stop();
    });

    await unlock();
    expect(speech()).toHaveLength(0);
    expect(result.current.playingId).toBeNull();
  });

  it('honours a stop clicked in the same gesture that unlocks the speaker', async () => {
    const { result, speech, unlock } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
    });
    document.body.addEventListener('click', () => result.current.stop(), { once: true });

    await unlock();

    expect(speech()).toHaveLength(0);
    expect(result.current.playingId).toBeNull();
  });

  it('keeps the blocked sentence silent when the unlocking gesture opens the microphone', async () => {
    const { result, speech, unlock } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
    });
    document.body.addEventListener('click', () => result.current.hold(), { once: true });

    await unlock();
    expect(speech()).toHaveLength(0);
    await act(async () => result.current.release());
    expect(speech()).toHaveLength(1);
    expect(result.current.playingId).toBe('first');
  });

  it('plays a manually selected blocked sentence once and keeps later arrivals', async () => {
    const { result, context, speech, unlock } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      result.current.enqueue('second', 'blob:second');
      await vi.advanceTimersByTimeAsync(1000);
    });
    document.body.addEventListener('click', () => result.current.playNow('first', 'blob:first'), {
      once: true,
    });

    await unlock();
    await unlock();
    expect(speech()).toHaveLength(1);
    expect(result.current.playingId).toBe('first');
    await act(async () => context.last()?.finish());
    expect(result.current.playingId).toBe('second');
    expect(speech()).toHaveLength(2);
  });

  it.each(['touch', 'Enter', ' '])(
    'waits for the activation click after %s so Play does not turn into Pause before the tap',
    async (activation) => {
      const { result, context, speech } = setup();
      await act(async () => {
        result.current.enqueue('first', 'blob:first');
        await vi.advanceTimersByTimeAsync(1000);
      });
      context.resumeBehaviour = 'run';

      await act(async () => {
        if (activation === 'touch') {
          fireEvent.touchEnd(document.body);
        } else {
          fireEvent.keyDown(document.body, { key: activation });
        }
      });
      expect(result.current.playingId).toBeNull();
      expect(speech()).toHaveLength(0);

      await act(async () => fireEvent.click(document.body));
      expect(result.current.playingId).toBe('first');
      expect(speech()).toHaveLength(1);
    }
  );

  it('retries a blocked arrival when typing unlocks the output', async () => {
    const { result, context, speech } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
    });
    context.resumeBehaviour = 'run';

    await act(async () => fireEvent.keyDown(document.body, { key: 'a' }));

    expect(result.current.playingId).toBe('first');
    expect(speech()).toHaveLength(1);
  });
});
