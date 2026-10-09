import type { GuestContent, GuestLanguage, PublicContent, StaffContent } from './content.types';

/** `fresh` reads past the browser's HTTP cache, for a reload after the server said content changed. */
export interface ContentReadOptions {
  fresh?: boolean;
}

/** Studio content as the gateway serves it. Every method rejects when there is none to use. */
export interface ContentSource {
  getPublic(options?: ContentReadOptions): Promise<PublicContent>;
  getGuestLanguages(sessionId: string): Promise<GuestLanguage[]>;
  getGuest(
    sessionId: string,
    language: string,
    options?: ContentReadOptions
  ): Promise<GuestContent>;
  /** Rejects with a 503 while Studio's login directory is down. */
  getStaff(options?: ContentReadOptions): Promise<StaffContent>;
}
