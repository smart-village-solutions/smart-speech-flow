import type { AxiosInstance } from 'axios';
import type { FeedbackSink } from './feedback.port';
import type { FeedbackAudience, FeedbackSubmission } from './feedback.types';

const SUBMIT_PATHS: Readonly<Record<FeedbackAudience, string>> = {
  installation: '/api/feedback',
  guest: '/api/feedback',
  // Filed under the token's tenant; the HTTP client sends the bearer to /api/admin/ only.
  staff: '/api/admin/feedback',
};

/**
 * The gateway forbids unknown fields (`extra="forbid"`), so the payload is
 * built key by key rather than spread from the submission.
 */
function toBody(submission: FeedbackSubmission): Record<string, unknown> {
  return {
    audience: submission.audience,
    // Installation feedback must carry no session; staff outside one sends none.
    ...(submission.sessionId === null ? {} : { session_id: submission.sessionId }),
    locale: submission.locale,
    form_source: submission.formSource,
    configuration_revision: submission.revision,
    answers: { ...submission.answers },
  };
}

export function createFeedbackRepository(http: AxiosInstance): FeedbackSink {
  return {
    async submit(submission: FeedbackSubmission) {
      await http.post(SUBMIT_PATHS[submission.audience], toBody(submission));
    },
  };
}
