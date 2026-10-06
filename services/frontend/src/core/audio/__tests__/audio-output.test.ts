import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAudioOutput } from '@/core/audio/audio-output';
import { asAudioContext, createFakeAudioContext } from '@/test/fakeAudioContext';

afterEach(() => vi.useRealTimers());

function setup(options: { webAudio?: boolean; session?: { type: string } | null } = {}) {
  const context = createFakeAudioContext();
  const createContext = vi.fn(() => (options.webAudio === false ? null : asAudioContext(context)));
  const output = createAudioOutput({
    createContext,
    session: options.session ?? null,
    resumeTimeoutMs: 1000,
  });
  return { context, createContext, output };
}

describe('createAudioOutput', () => {
  it('creates one context and keeps it', () => {
    const { output, createContext } = setup();

    expect(output.context()).toBe(output.context());
    expect(createContext).toHaveBeenCalledTimes(1);
  });

  it('throws from context() when the browser has no Web Audio', () => {
    const { output } = setup({ webAudio: false });

    expect(() => output.context()).toThrow('Web Audio is unavailable');
  });

  it('resumes a suspended context and sounds silence inside the gesture', () => {
    const { output, context } = setup();

    output.unlock();

    expect(context.resume).toHaveBeenCalledTimes(1);
    expect(context.started).toHaveLength(1);
    expect(context.last()?.buffer?.duration).toBeLessThan(0.001);
  });

  it('leaves a running context alone', () => {
    const { output, context } = setup();
    context.state = 'running';

    output.unlock();

    expect(context.resume).not.toHaveBeenCalled();
    expect(context.started).toHaveLength(0);
  });

  it('unlocks again after iOS interrupts the context', () => {
    const { output, context } = setup();
    context.state = 'interrupted';

    output.unlock();

    expect(context.resume).toHaveBeenCalledTimes(1);
  });

  it('ignores a gesture when the browser has no Web Audio', () => {
    const { output } = setup({ webAudio: false });

    expect(() => output.unlock()).not.toThrow();
  });

  it('reports a context that resumes as running', async () => {
    const { output } = setup();

    await expect(output.ensureRunning()).resolves.toBe(true);
  });

  it('gives up on a resume that never settles rather than waiting forever', async () => {
    vi.useFakeTimers();
    const { output, context } = setup();
    context.resumeBehaviour = 'hang';

    const running = output.ensureRunning();
    await vi.advanceTimersByTimeAsync(1000);

    await expect(running).resolves.toBe(false);
  });

  // A burst of arrivals before the first tap would otherwise show each bubble
  // playing silence for the whole timeout, one after another.
  it('answers at once after a refusal, until the next gesture', async () => {
    vi.useFakeTimers();
    const { output, context } = setup();
    context.resumeBehaviour = 'hang';

    const first = output.ensureRunning();
    await vi.advanceTimersByTimeAsync(1000);
    await expect(first).resolves.toBe(false);

    await expect(output.ensureRunning()).resolves.toBe(false);

    context.resumeBehaviour = 'run';
    output.unlock();
    await expect(output.ensureRunning()).resolves.toBe(true);
  });

  it('reports no output when the browser has no Web Audio', async () => {
    const { output } = setup({ webAudio: false });

    await expect(output.ensureRunning()).resolves.toBe(false);
  });

  it('claims the speaker past the iOS silent switch only while speech sounds', () => {
    const session = { type: 'auto' };
    const { output } = setup({ session });

    output.setSounding(true);
    expect(session.type).toBe('playback');

    output.setSounding(false);
    expect(session.type).toBe('auto');
  });

  it('does without an audio session where the browser has none', () => {
    const { output } = setup({ session: null });

    expect(() => output.setSounding(true)).not.toThrow();
  });
});
