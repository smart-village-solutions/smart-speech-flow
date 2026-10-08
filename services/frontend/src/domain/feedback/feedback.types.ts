/** Star fields are 1-5, netPromoterScore is 0-10, matching the overlay's controls. */
export interface FeedbackSubmission {
  translationQuality: number;
  performance: number;
  usability: number;
  netPromoterScore: number;
  improvements: string;
  sessionId: string | null;
}

/**
 * Where the sheet was opened, which decides the audience: the start and login
 * pages give installation feedback, guest screens carry their session, staff
 * screens carry theirs when they have one.
 */
export type FeedbackOrigin =
  | { kind: 'public' }
  | { kind: 'guest'; sessionId: string }
  | { kind: 'staff'; sessionId: string | null };
