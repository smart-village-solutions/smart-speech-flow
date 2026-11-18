import type { ReactNode } from 'react';
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PlaybackProvider } from '@/app/providers/PlaybackProvider';
import { usePlayback } from '@/app/providers/playback';
import { ServicesProvider } from '@/app/providers/ServicesProvider';
import { createServices } from '@/app/providers/services';
import { readConfig } from '@/app/config/env';
import { useReadAloud } from '@/features/recording/useReadAloud';
import { createAudioOutput } from '@/core/audio/audio-output';
import { createWebAudioPlayer } from '@/core/audio/web-audio-player';
import { asAudioContext, createFakeAudioContext } from '@/test/fakeAudioContext';

afterEach(() => vi.useRealTimers());

function setup(requestId: string | null = null) {
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
  const services = createServices(readConfig({}), () => 'en');
  const view = renderHook(
    ({ requestId }: { requestId: string | null }) => {
      useReadAloud('SESSION1', requestId, null);
      return usePlayback();
    },
    {
      initialProps: { requestId },
      wrapper: ({ children }: { children: ReactNode }) => (
        <ServicesProvider services={services}>
          <PlaybackProvider output={output} player={player} clips={clips}>
            <button data-testid="activation">Play</button>
            <textarea data-testid="text" />
            {children}
          </PlaybackProvider>
        </ServicesProvider>
      ),
    }
  );
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
  it.each([
    { key: ' ', element: <a href="#test">Link</a> },
    { key: 'Enter', element: <input type="checkbox" /> },
  ])('retries $key when this control does not generate a click', async ({ key, element }) => {
    const { result, context, speech } = setup();
    const target = render(element).container.firstElementChild!;
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
    });
    context.resumeBehaviour = 'run';
    await act(async () => fireEvent.keyDown(target, { key }));
    expect(speech()).toHaveLength(1);
  });

  it('retries when a control prevents its native activation click', async () => {
    const { result, context, speech } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
    });
    const button = screen.getByTestId('activation');
    button.addEventListener('keydown', (event) => event.preventDefault(), { once: true });
    context.resumeBehaviour = 'run';
    await act(async () => fireEvent.keyDown(button, { key: 'Enter' }));
    expect(speech()).toHaveLength(1);
  });

  it('clears the browser block when the bubble explicitly resumes playback', async () => {
    const { result, context, speech, unlock } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
    });
    document.body.addEventListener('click', () => result.current.resume(), { once: true });
    await unlock();
    expect(speech()).toHaveLength(1);
    await act(async () => context.last()?.finish());
    await act(async () => result.current.enqueue('second', 'blob:second'));
    expect(speech()).toHaveLength(2);
    expect(result.current.playingId).toBe('second');
  });
  it.each(['Enter', ' '])(
    'retries after %s in the conversation textarea without an activation click',
    async (key) => {
      const { result, context, speech } = setup();
      await act(async () => {
        result.current.enqueue('first', 'blob:first');
        await vi.advanceTimersByTimeAsync(1000);
      });
      context.resumeBehaviour = 'run';
      await act(async () => fireEvent.keyDown(screen.getByTestId('text'), { key }));
      expect(speech()).toHaveLength(1);
      expect(result.current.paused).toBe(false);
    }
  );

  it('cancels a blocked consent reading when its question closes, preserving later peer audio', async () => {
    const { result, rerender, speech, unlock } = setup('r1');
    await act(async () => {
      result.current.playNow('consent-r1', 'blob:consent');
      await vi.advanceTimersByTimeAsync(1000);
    });
    rerender({ requestId: null });
    await act(async () => result.current.enqueue('peer', 'blob:peer'));
    await unlock();
    expect(result.current.playingId).toBe('peer');
    expect(speech()).toHaveLength(1);
  });

  it('plays the first blocked arrival after an ordinary gesture without tapping Play', async () => {
    const { result, speech, unlock } = setup();
    await act(async () => {
      result.current.enqueue('first', 'blob:first');
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(speech()).toHaveLength(0);
    expect(result.current.playingId).toBe('first');
    expect(result.current.paused).toBe(true);

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
          fireEvent.keyDown(screen.getByTestId('activation'), { key: activation });
        }
      });
      expect(result.current.playingId).toBe('first');
      expect(result.current.paused).toBe(true);
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
