/** Star fields are 1-5, netPromoterScore is 0-10, matching the overlay's controls. */
export interface FeedbackSubmission {
  translationQuality: number;
  performance: number;
  usability: number;
  netPromoterScore: number;
  improvements: string;
  sessionId: string | null;
}
