import type { FeedbackOrigin } from './feedback.types';

/**
 * Guest routes always carry a session, but useParams types it optional. Without
 * one there is no session to file guest feedback under, so it counts as public,
 * which sends the same null session the screens sent before.
 */
export function guestOrigin(sessionId: string | undefined): FeedbackOrigin {
  return sessionId ? { kind: 'guest', sessionId } : { kind: 'public' };
}

export function sessionIdOf(origin: FeedbackOrigin): string | null {
  return origin.kind === 'public' ? null : origin.sessionId;
}
