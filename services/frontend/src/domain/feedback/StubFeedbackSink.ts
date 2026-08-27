import type { FeedbackSink } from './feedback.port';
import type { FeedbackSubmission } from './feedback.types';

export function createStubFeedbackSink(
  recorder: (submission: FeedbackSubmission) => void = () => {}
): FeedbackSink {
  return {
    async submit(submission) {
      recorder(submission);
    },
  };
}
