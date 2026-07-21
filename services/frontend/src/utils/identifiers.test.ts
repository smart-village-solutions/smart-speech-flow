import { describe, expect, it } from 'vitest';
import {
  buildWebSocketUrl,
  requirePathIdentifier,
  sessionPath,
  validatePathIdentifier,
} from './identifiers';

describe('path identifier validation', () => {
  it('accepts the session identifiers produced by the UI', () => {
    expect(validatePathIdentifier('AB12CD34', 'session')).toBe(true);
    expect(sessionPath('AB12CD34')).toBe('/api/session/AB12CD34');
  });

  it('rejects path injection before a request URL is constructed', () => {
    expect(validatePathIdentifier('../admin', 'session')).toBe(false);
    expect(() => requirePathIdentifier('../admin', 'session')).toThrow('Invalid session identifier');
    expect(() => sessionPath('AB12/../')).toThrow('Invalid session identifier');
  });

  it('allows only ws and wss base URLs and clears injected URL parts', () => {
    expect(buildWebSocketUrl('wss://example.test/base?token=secret', 'AB12CD34', 'admin'))
      .toBe('wss://example.test/base/ws/AB12CD34/admin');
    expect(() => buildWebSocketUrl('https://example.test', 'AB12CD34', 'admin'))
      .toThrow('WebSocket base URL must use ws or wss');
  });
});
