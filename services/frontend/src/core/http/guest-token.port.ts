/** The token that makes this browser a session's one guest. One session at a time. */
export interface GuestTokenStore {
  /** The token held for this session, or null for any other. */
  read(sessionId: string): string | null;
  save(sessionId: string, token: string): void;
}
