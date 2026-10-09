import { describe, expect, it } from 'vitest';
import { audienceOf, guestOrigin, sessionIdOf } from '@/domain/feedback/feedbackOrigin';

describe('guestOrigin', () => {
  it('files guest feedback under the session of the route', () => {
    expect(guestOrigin('A1B2C3D4')).toEqual({ kind: 'guest', sessionId: 'A1B2C3D4' });
  });

  it.each([undefined, ''])('falls back to public feedback without a session (%j)', (sessionId) => {
    expect(guestOrigin(sessionId)).toEqual({ kind: 'public' });
  });
});

describe('sessionIdOf', () => {
  it.each([
    [{ kind: 'public' } as const, null],
    [{ kind: 'guest', sessionId: 'A1B2C3D4' } as const, 'A1B2C3D4'],
    [{ kind: 'staff', sessionId: 'E5F6G7H8' } as const, 'E5F6G7H8'],
    [{ kind: 'staff', sessionId: null } as const, null],
  ])('reads the session of %j', (origin, expected) => {
    expect(sessionIdOf(origin)).toBe(expected);
  });
});

describe('audienceOf', () => {
  it.each([
    [{ kind: 'public' } as const, 'installation'],
    [{ kind: 'guest', sessionId: 'A1B2C3D4' } as const, 'guest'],
    [{ kind: 'staff', sessionId: 'E5F6G7H8' } as const, 'staff'],
    [{ kind: 'staff', sessionId: null } as const, 'staff'],
  ])('files feedback opened from %j under its audience', (origin, expected) => {
    expect(audienceOf(origin)).toBe(expected);
  });
});
