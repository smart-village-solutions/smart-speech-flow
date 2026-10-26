/**
 * Remembers which staff screen to reopen after a redirect to Keycloak and back,
 * which reloads the app and with it every piece of React state.
 */
export interface ResumeMemory {
  remember(view: string): void;
  /** Returns the remembered view once, then forgets it. */
  take(): string | null;
}
