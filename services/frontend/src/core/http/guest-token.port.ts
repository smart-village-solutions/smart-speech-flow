/** The token that makes this browser a session's one guest. One session at a time. */
export interface GuestTokenStore {
  read(): string | null;
  save(sessionId: string, token: string): void;
}
