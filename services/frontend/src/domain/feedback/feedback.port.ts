import type { FeedbackSubmission } from './feedback.types';

/**
 * `Promise<void>` on purpose: the confirmation identifier the gateway returns
 * is an internal handle, not something the sheet shows or the customer needs.
 * Failures arrive as the `AppError` the HTTP client normalises, which is what
 * the sheet turns into a reason and a retry.
 */
export interface FeedbackSink {
  submit(submission: FeedbackSubmission): Promise<void>;
}
