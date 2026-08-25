import type { FeedbackSubmission } from './feedback.types';

/**
 * The gateway has no feedback endpoint yet (docs/frontend/API_GAPS.md). When
 * POST /api/feedback exists, an ApiFeedbackSink replaces the stub in the
 * provider and no component changes.
 */
export interface FeedbackSink {
  submit(submission: FeedbackSubmission): Promise<void>;
}
