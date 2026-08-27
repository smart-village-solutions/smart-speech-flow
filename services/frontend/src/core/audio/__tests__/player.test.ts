import { describe, expect, it, vi } from 'vitest';
import { createDomAudioPlayer } from '@/core/audio/player.port';

/** A stand-in for HTMLAudioElement: jsdom implements neither play nor timing. */
function fakeElement() {
  const listeners = new Map<string, Set<EventListener>>();

  const element = {
    srcAssignments: 0,
    _src: '',
    get src() {
      return this._src;
    },
    set src(value: string) {
      this._src = value;
      this.srcAssignments += 1;
    },
    currentTime: 0,
    duration: 10,
    play: vi.fn().mockResolvedValue(undefined),
    pause: vi.fn(),
    addEventListener: (type: string, handler: EventListener) => {
      const set = listeners.get(type) ?? new Set();
      set.add(handler);
      listeners.set(type, set);
    },
    removeEventListener: (type: string, handler: EventListener) => {
      listeners.get(type)?.delete(handler);
    },
    emit(type: string) {
      for (const handler of listeners.get(type) ?? []) {
        handler(new Event(type));
      }
    },
    listenerCount: (type: string) => listeners.get(type)?.size ?? 0,
  };

  return element;
}

describe('createDomAudioPlayer', () => {
  it('plays a url from the beginning', async () => {
    const element = fakeElement();
    const player = createDomAudioPlayer(element as unknown as HTMLAudioElement);

    element.currentTime = 4;
    await player.play('/api/audio/m1.wav');

    expect(element.src).toBe('/api/audio/m1.wav');
    expect(element.currentTime).toBe(0);
    expect(element.play).toHaveBeenCalledTimes(1);
  });

  it('restarts from zero when the same url is played again', async () => {
    const element = fakeElement();
    const player = createDomAudioPlayer(element as unknown as HTMLAudioElement);

    await player.play('/api/audio/m1.wav');
    element.currentTime = 7;
    await player.play('/api/audio/m1.wav');

    expect(element.currentTime).toBe(0);
    expect(element.play).toHaveBeenCalledTimes(2);
    // Reassigning src would re-download the clip instead of replaying it.
    expect(element.srcAssignments).toBe(1);
  });

  it('reloads a clip that previously failed', async () => {
    const element = fakeElement();
    const player = createDomAudioPlayer(element as unknown as HTMLAudioElement);

    await player.play('/api/audio/m1.wav');
    element.emit('error');
    await player.play('/api/audio/m1.wav');

    expect(element.srcAssignments).toBe(2);
  });

  it('surfaces a rejected play as a rejected promise', async () => {
    const element = fakeElement();
    element.play.mockRejectedValueOnce(new Error('NotAllowedError'));
    const player = createDomAudioPlayer(element as unknown as HTMLAudioElement);

    await expect(player.play('/api/audio/m1.wav')).rejects.toThrow('NotAllowedError');
  });

  it('reports progress as a fraction of the duration', async () => {
    const element = fakeElement();
    const player = createDomAudioPlayer(element as unknown as HTMLAudioElement);
    const progress = vi.fn();
    player.onProgress(progress);

    element.currentTime = 2.5;
    element.emit('timeupdate');

    expect(progress).toHaveBeenCalledWith(0.25);
  });

  it('reports no progress while the duration is unknown', () => {
    const element = fakeElement();
    element.duration = Number.NaN;
    const player = createDomAudioPlayer(element as unknown as HTMLAudioElement);
    const progress = vi.fn();
    player.onProgress(progress);

    element.emit('timeupdate');

    expect(progress).not.toHaveBeenCalled();
  });

  it('notifies ended and error listeners', () => {
    const element = fakeElement();
    const player = createDomAudioPlayer(element as unknown as HTMLAudioElement);
    const ended = vi.fn();
    const failed = vi.fn();
    player.onEnded(ended);
    player.onError(failed);

    element.emit('ended');
    element.emit('error');

    expect(ended).toHaveBeenCalledTimes(1);
    expect(failed).toHaveBeenCalledTimes(1);
  });

  it('unsubscribes listeners', () => {
    const element = fakeElement();
    const player = createDomAudioPlayer(element as unknown as HTMLAudioElement);
    const ended = vi.fn();

    const off = player.onEnded(ended);
    off();
    element.emit('ended');

    expect(ended).not.toHaveBeenCalled();
    expect(element.listenerCount('ended')).toBe(0);
  });

  it('stops playback and parks the element at the start', async () => {
    const element = fakeElement();
    const player = createDomAudioPlayer(element as unknown as HTMLAudioElement);

    await player.play('/api/audio/m1.wav');
    element.currentTime = 3;
    player.stop();

    expect(element.pause).toHaveBeenCalledTimes(1);
    expect(element.currentTime).toBe(0);
  });
});
