import { describe, expect, it } from 'vitest';
import { isSafeHttpsUrl, resolveApiUrl } from '@/core/http/url';

describe('resolveApiUrl', () => {
  // In production the gateway has its own origin at api.dialog.kassel.de, so
  // a gateway path left relative is fetched from the SPA origin, where no audio exists.
  it('puts a gateway path on the api origin', () => {
    expect(
      resolveApiUrl(
        'https://ssf.example',
        '/api/admin/session/A1B2C3D4/audio/m1/translated.wav'
      )
    ).toBe(
      'https://ssf.example/api/admin/session/A1B2C3D4/audio/m1/translated.wav'
    );
  });

  it('leaves the path alone in development, where the dev server proxies /api', () => {
    expect(resolveApiUrl('', '/clips/m1.wav')).toBe('/clips/m1.wav');
  });

  it('does not double the separator', () => {
    expect(resolveApiUrl('https://ssf.example/', '/clips/m1.wav')).toBe(
      'https://ssf.example/clips/m1.wav'
    );
  });

  it('adds the separator a relative path is missing', () => {
    expect(resolveApiUrl('https://ssf.example', 'clips/m1.wav')).toBe(
      'https://ssf.example/clips/m1.wav'
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

describe('isSafeHttpsUrl', () => {
  it('accepts an absolute https URL', () => {
    expect(isSafeHttpsUrl('https://dialog.kassel.de/assets/Logo.png')).toBe(true);
  });

  it.each([
    'http://dialog.kassel.de/',
    'javascript:alert(1)',
    'data:image/png;base64,AAAA',
    'https://user:pass@dialog.kassel.de/',
    'https://user@dialog.kassel.de/',
    '/assets/Logo.png',
    '',
  ])('rejects %j', (value) => {
    expect(isSafeHttpsUrl(value)).toBe(false);
  });
});
