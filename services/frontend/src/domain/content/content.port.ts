import type { GuestContent, GuestLanguage, PublicContent, StaffContent } from './content.types';

/** Studio content as the gateway serves it. Every method rejects when there is none to use. */
export interface ContentSource {
  getPublic(): Promise<PublicContent>;
  getGuestLanguages(sessionId: string): Promise<GuestLanguage[]>;
  getGuest(sessionId: string, language: string): Promise<GuestContent>;
  /** Rejects with a 503 while Studio's login directory is down. */
  getStaff(): Promise<StaffContent>;
}
