import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createBrowserClipLoader,
  createClipLoader,
  type ClipLoaderDeps,
} from '@/core/audio/clips';
import { MIN_BAR_HEIGHT } from '@/core/audio/levels';
import { createHttpClient } from '@/core/http/client';
import { readConfig } from '@/app/config/env';
import { getAdminAccessToken } from '@/app/auth/keycloak';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

afterEach(() => vi.unstubAllGlobals());

function deps(overrides: Partial<ClipLoaderDeps> = {}) {
  let issued = 0;
  const nextUrl = () => {
    issued += 1;
    return `blob:clip-${issued}`;
  };

  const base: ClipLoaderDeps = {
    fetchBytes: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
    decode: vi.fn().mockResolvedValue(new Float32Array([0.5, -0.5, 0.5, -0.5])),
    createObjectUrl: vi.fn(nextUrl),
    revokeObjectUrl: vi.fn(),
    bars: 4,
    ...overrides,
  };

  return base;
}

describe('createClipLoader', () => {
  it('returns an object url to play and peaks to draw', async () => {
    const loader = createClipLoader(deps());

    const clip = await loader.load('/clips/m1.wav');

    expect(clip.objectUrl).toBe('blob:clip-1');
    expect(clip.peaks).toHaveLength(4);
  });

  it('downloads a clip once, however often it is asked for', async () => {
    const d = deps();
    const loader = createClipLoader(d);

    await loader.load('/clips/m1.wav');
    await loader.load('/clips/m1.wav');

    expect(d.fetchBytes).toHaveBeenCalledTimes(1);
  });

  it('collapses concurrent requests into a single download', async () => {
    const d = deps();
    const loader = createClipLoader(d);

    await Promise.all([loader.load('/clips/m1.wav'), loader.load('/clips/m1.wav')]);

    expect(d.fetchBytes).toHaveBeenCalledTimes(1);
  });

  it('keeps clips apart', async () => {
    const d = deps();
    const loader = createClipLoader(d);

    const first = await loader.load('/clips/m1.wav');
    const second = await loader.load('/clips/m2.wav');

    expect(first.objectUrl).not.toBe(second.objectUrl);
    expect(d.fetchBytes).toHaveBeenCalledTimes(2);
  });

  it('peeks nothing until the clip has arrived', async () => {
    const loader = createClipLoader(deps());

    expect(loader.peek('/clips/m1.wav')).toBeNull();

    await loader.load('/clips/m1.wav');

    expect(loader.peek('/clips/m1.wav')?.objectUrl).toBe('blob:clip-1');
  });

  it('reports a failed download without caching the failure', async () => {
    const d = deps({
      fetchBytes: vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(new ArrayBuffer(8)),
    });
    const loader = createClipLoader(d);

    await expect(loader.load('/clips/m1.wav')).rejects.toThrow('offline');
    expect(loader.peek('/clips/m1.wav')).toBeNull();

    // A later attempt is allowed to try again.
    await expect(loader.load('/clips/m1.wav')).resolves.toMatchObject({
      objectUrl: 'blob:clip-1',
    });
  });

  it('does not hand out an object url for a clip it could not decode', async () => {
    const d = deps({ decode: vi.fn().mockRejectedValue(new Error('bad wav')) });
    const loader = createClipLoader(d);

    await expect(loader.load('/clips/m1.wav')).rejects.toThrow('bad wav');
    expect(loader.peek('/clips/m1.wav')).toBeNull();
  });

  it('draws silence as the floor', async () => {
    const loader = createClipLoader(deps({ decode: vi.fn().mockResolvedValue(new Float32Array(16)) }));

    const clip = await loader.load('/clips/m1.wav');

    expect(clip.peaks).toEqual(new Array(4).fill(MIN_BAR_HEIGHT));
  });

  it('releases every object url when disposed', async () => {
    const d = deps();
    const loader = createClipLoader(d);

    await loader.load('/clips/m1.wav');
    await loader.load('/clips/m2.wav');
    loader.dispose();

    expect(d.revokeObjectUrl).toHaveBeenCalledWith('blob:clip-1');
    expect(d.revokeObjectUrl).toHaveBeenCalledWith('blob:clip-2');
    expect(loader.peek('/clips/m1.wav')).toBeNull();
  });
});

describe('createBrowserClipLoader', () => {
  it('downloads admin audio through the bearer-token HTTP client', async () => {
    vi.mocked(getAdminAccessToken).mockResolvedValue('tenant-token');
    const config = readConfig({ VITE_API_BASE_URL: 'http://api.test' });
    const http = createHttpClient(config, () => 'en');
    let authorization: string | undefined;
    http.defaults.adapter = async (request) => {
      authorization = request.headers.get('Authorization')?.toString();
      return {
        data: new ArrayBuffer(8),
        status: 200,
        statusText: 'OK',
        headers: {},
        config: request,
      };
    };
    vi.stubGlobal(
      'AudioContext',
      class {
        async decodeAudioData() {
          return { getChannelData: () => new Float32Array([0.5, -0.5]) };
        }
      }
    );
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn().mockReturnValue('blob:authenticated-audio'),
    });

    const loader = createBrowserClipLoader(http);
    const clip = await loader.load(
      'http://api.test/api/admin/session/A1B2C3D4/audio/m1/translated.wav'
    );

    expect(authorization).toBe('Bearer tenant-token');
    expect(clip.objectUrl).toBe('blob:authenticated-audio');
  });
});
