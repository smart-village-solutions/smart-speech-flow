import { describe, expect, it } from 'vitest';
import { resolveApiUrl } from '@/core/http/url';

describe('resolveApiUrl', () => {
  // In production the SPA is served from translate.smart-village.solutions and
  // the gateway from ssf.smart-village.solutions, so a gateway path left
  // relative is fetched from the SPA origin, where no audio exists.
  it('puts a gateway path on the api origin', () => {
    expect(resolveApiUrl('https://ssf.example', '/api/audio/m1.wav')).toBe(
      'https://ssf.example/api/audio/m1.wav'
    );
  });

  it('leaves the path alone in development, where the dev server proxies /api', () => {
    expect(resolveApiUrl('', '/api/audio/m1.wav')).toBe('/api/audio/m1.wav');
  });

  it('does not double the separator', () => {
    expect(resolveApiUrl('https://ssf.example/', '/api/audio/m1.wav')).toBe(
      'https://ssf.example/api/audio/m1.wav'
    );
  });

  it('adds the separator a relative path is missing', () => {
    expect(resolveApiUrl('https://ssf.example', 'api/audio/m1.wav')).toBe(
      'https://ssf.example/api/audio/m1.wav'
    );
  });

  // The gateway is free to answer with a fully qualified url, or a blob/data
  // url in a test. Neither may be re-based.
  it('leaves an absolute url untouched', () => {
    expect(resolveApiUrl('https://ssf.example', 'https://cdn.example/m1.wav')).toBe(
      'https://cdn.example/m1.wav'
    );
    expect(resolveApiUrl('https://ssf.example', '//cdn.example/m1.wav')).toBe(
      '//cdn.example/m1.wav'
    );
    expect(resolveApiUrl('https://ssf.example', 'blob:abc123')).toBe('blob:abc123');
  });

  it('leaves an empty url alone', () => {
    expect(resolveApiUrl('https://ssf.example', '')).toBe('');
  });
});
