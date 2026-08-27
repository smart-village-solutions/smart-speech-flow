export interface ConsentRecord {
  sessionId: string;
  /** Opt-in to retaining conversation data for up to 180 days. */
  dataRetentionConsent: boolean;
  recordedAt: string;
}
