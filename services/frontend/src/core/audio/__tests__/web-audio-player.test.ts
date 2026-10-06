import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAudioOutput } from '@/core/audio/audio-output';
import { createWebAudioPlayer } from '@/core/audio/web-audio-player';
import { asAudioContext, createFakeAudioContext } from '@/test/fakeAudioContext';

afterEach(() => vi.useRealTimers());

function setup() {
  const context = createFakeAudioContext();
  context.state = 'running';
  const session = { type: 'auto' };
  const output = createAudioOutput({
    createContext: () => asAudioContext(context),
    session,
    resumeTimeoutMs: 1000,
  });
  const fetchBytes = vi.fn<(url: string) => Promise<ArrayBuffer>>(async () => new ArrayBuffer(8));
  const player = createWebAudioPlayer(output, fetchBytes);
  return { context, session, fetchBytes, player };
}

describe('createWebAudioPlayer', () => {
  it('refuses a protected gateway url instead of issuing a bare request', async () => {
    const { player, fetchBytes, context } = setup();

    await expect(
      player.play('/api/admin/session/A1B2C3D4/audio/m1/translated.wav')
    ).rejects.toThrow('buffered');

    expect(fetchBytes).not.toHaveBeenCalled();
    expect(context.started).toHaveLength(0);
  });

  it('plays a clip from the beginning through the speaker', async () => {
    const { player, context } = setup();

    await player.play('blob:m1');

    const source = context.last();
    expect(source?.offset).toBe(0);
    expect(source?.buffer?.duration).toBe(10);
    expect(source?.connect).toHaveBeenCalledWith(context.destination);
  });

  it('decodes a clip once, however often it is played', async () => {
    const { player, fetchBytes, context } = setup();

    await player.play('blob:m1');
    await player.play('blob:m1');

    expect(fetchBytes).toHaveBeenCalledTimes(1);
    expect(context.decodeAudioData).toHaveBeenCalledTimes(1);
    expect(context.started).toHaveLength(2);
  });

  // Decoded PCM is several times the size of the WAV; a long conversation
  // must not keep every clip of it in memory.
  it('keeps only the most recently played clips decoded', async () => {
    const { player, fetchBytes } = setup();

    for (let clip = 1; clip <= 9; clip += 1) {
      await player.play(`blob:m${clip}`);
    }
    await player.play('blob:m9');
    expect(fetchBytes).toHaveBeenCalledTimes(9);

    await player.play('blob:m1');
    expect(fetchBytes).toHaveBeenCalledTimes(10);
  });

  it('keeps a replayed clip among the recent ones', async () => {
    const { player, fetchBytes } = setup();

    await player.play('blob:m1');
    for (let clip = 2; clip <= 8; clip += 1) {
      await player.play(`blob:m${clip}`);
    }
    await player.play('blob:m1');
    await player.play('blob:m9');
    await player.play('blob:m1');

    expect(fetchBytes).toHaveBeenCalledTimes(9);
  });

  it('keeps a fresh decode when an evicted one for the same clip fails late', async () => {
    const { player, fetchBytes } = setup();
    let failFirst!: (error: Error) => void;
    fetchBytes.mockReturnValueOnce(
      new Promise((_resolve, reject) => {
        failFirst = reject;
      })
    );

    const first = player.play('blob:m1');
    for (let clip = 2; clip <= 9; clip += 1) {
      await player.play(`blob:m${clip}`);
    }
    await player.play('blob:m1');
    failFirst(new Error('offline'));
    await expect(first).rejects.toThrow();
    await player.play('blob:m1');

    expect(fetchBytes).toHaveBeenCalledTimes(10);
  });

  it('rejects a clip that cannot be decoded, and tries it afresh next time', async () => {
    const { player, fetchBytes, context } = setup();
    context.decodeAudioData.mockRejectedValueOnce(new Error('EncodingError'));

    await expect(player.play('blob:m1')).rejects.toThrow('EncodingError');
    await player.play('blob:m1');

    expect(fetchBytes).toHaveBeenCalledTimes(2);
    expect(context.started).toHaveLength(1);
  });

  it('rejects, without sounding, while the browser keeps the output locked', async () => {
    vi.useFakeTimers();
    const { player, context, session } = setup();
    context.state = 'suspended';
    context.resumeBehaviour = 'hang';

    const playing = player.play('blob:m1');
    const settled = expect(playing).rejects.toThrow('locked');
    await vi.advanceTimersByTimeAsync(1000);
    await settled;

    expect(context.started).toHaveLength(0);
    expect(session.type).toBe('auto');
  });

  it('holds the speaker past the silent switch only while a clip sounds', async () => {
    const { player, context, session } = setup();

    await player.play('blob:m1');
    expect(session.type).toBe('playback');

    context.last()?.finish();
    expect(session.type).toBe('auto');
  });

  it('reports a clip reaching its end', async () => {
    const { player, context } = setup();
    const ended = vi.fn();
    player.onEnded(ended);

    await player.play('blob:m1');
    context.last()?.finish();

    expect(ended).toHaveBeenCalledTimes(1);
  });

  it('silences on stop without reporting an end', async () => {
    const { player, context, session } = setup();
    const ended = vi.fn();
    player.onEnded(ended);

    await player.play('blob:m1');
    player.stop();

    expect(context.last()?.stopped).toBe(true);
    expect(ended).not.toHaveBeenCalled();
    expect(session.type).toBe('auto');
  });

  it('cuts the previous clip short, without an end, when another starts', async () => {
    const { player, context } = setup();
    const ended = vi.fn();
    player.onEnded(ended);

    await player.play('blob:m1');
    const first = context.last();
    await player.play('blob:m2');

    expect(first?.stopped).toBe(true);
    expect(ended).not.toHaveBeenCalled();
  });

  it('carries on from where a pause stopped it', async () => {
    const { player, context } = setup();
    const ended = vi.fn();
    player.onEnded(ended);

    context.currentTime = 100;
    await player.play('blob:m1');
    context.currentTime = 104;
    player.pause();
    context.currentTime = 200;
    await player.resume();

    expect(context.started).toHaveLength(2);
    expect(context.started[0]?.stopped).toBe(true);
    expect(context.last()?.offset).toBe(4);
    expect(ended).not.toHaveBeenCalled();
  });

  it('abandons a play still decoding when it is paused', async () => {
    const { player, context } = setup();
    let finishDecode!: (buffer: { duration: number }) => void;
    context.decodeAudioData.mockReturnValueOnce(
      new Promise((resolve) => {
        finishDecode = resolve;
      })
    );

    const playing = player.play('blob:m1');
    await vi.waitFor(() => expect(context.decodeAudioData).toHaveBeenCalled());
    player.pause();
    finishDecode({ duration: 10 });

    await expect(playing).rejects.toThrow('superseded');
    expect(context.started).toHaveLength(0);
  });

  it('abandons a play still decoding when it is stopped', async () => {
    const { player, context } = setup();
    let finishDecode!: (buffer: { duration: number }) => void;
    context.decodeAudioData.mockReturnValueOnce(
      new Promise((resolve) => {
        finishDecode = resolve;
      })
    );

    const playing = player.play('blob:m1');
    await vi.waitFor(() => expect(context.decodeAudioData).toHaveBeenCalled());
    player.stop();
    finishDecode({ duration: 10 });

    await expect(playing).rejects.toThrow('superseded');
    expect(context.started).toHaveLength(0);
  });

  it('resumes the clip that was playing, not one overtaken while it decoded', async () => {
    const { player, context } = setup();
    let finishFirst!: (buffer: { duration: number }) => void;
    context.decodeAudioData
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finishFirst = resolve;
        })
      )
      .mockResolvedValueOnce({ duration: 20 });

    const first = player.play('blob:m1');
    await vi.waitFor(() => expect(context.decodeAudioData).toHaveBeenCalledTimes(1));
    await player.play('blob:m2');
    finishFirst({ duration: 10 });
    await expect(first).rejects.toThrow('superseded');

    player.pause();
    await player.resume();

    expect(context.last()?.buffer?.duration).toBe(20);
  });

  it('reports progress while a clip sounds, and none after it stops', async () => {
    vi.useFakeTimers();
    const { player, context } = setup();
    const progress = vi.fn();
    player.onProgress(progress);

    context.currentTime = 50;
    await player.play('blob:m1');
    context.currentTime = 52.5;
    await vi.advanceTimersByTimeAsync(250);

    expect(progress).toHaveBeenLastCalledWith(0.25);

    player.stop();
    progress.mockClear();
    await vi.advanceTimersByTimeAsync(1000);

    expect(progress).not.toHaveBeenCalled();
  });

  it('stops calling a handler once it unsubscribes', async () => {
    const { player, context } = setup();
    const ended = vi.fn();
    const off = player.onEnded(ended);

    off();
    await player.play('blob:m1');
    context.last()?.finish();

    expect(ended).not.toHaveBeenCalled();
  });
});
