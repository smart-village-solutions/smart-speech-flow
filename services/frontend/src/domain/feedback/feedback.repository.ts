import type { AxiosInstance } from 'axios';
import type { FeedbackSink } from './feedback.port';
import type { FeedbackSubmission } from './feedback.types';

/**
 * Identifies the question set these ratings answered, so a later form revision
 * does not silently pool incomparable numbers. The gateway defaults it during
 * rollout, but a client that renders the questions is the only thing that
 * knows which version it rendered.
 */
const FORM_VERSION = 'v1';

/**
 * The gateway forbids unknown fields (`extra="forbid"`), so the payload is
 * built key by key rather than spread from the submission.
 */
export function createFeedbackRepository(http: AxiosInstance): FeedbackSink {
  return {
    async submit(submission: FeedbackSubmission) {
      const improvements = submission.improvements.trim();

      await http.post('/api/feedback', {
        session_id: submission.sessionId,
        translation_quality: submission.translationQuality,
        performance: submission.performance,
        usability: submission.usability,
        net_promoter_score: submission.netPromoterScore,
        improvements: improvements === '' ? null : improvements,
        form_version: FORM_VERSION,
      });
    },
  };
}
