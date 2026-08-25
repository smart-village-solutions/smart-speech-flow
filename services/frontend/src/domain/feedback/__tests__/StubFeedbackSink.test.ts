import { describe, expect, it, vi } from 'vitest';
import { createStubFeedbackSink } from '@/domain/feedback/StubFeedbackSink';
import type { FeedbackSubmission } from '@/domain/feedback/feedback.types';

const submission: FeedbackSubmission = {
  translationQuality: 5,
  performance: 4,
  usability: 5,
  netPromoterScore: 9,
  improvements: 'more languages',
  sessionId: 'A1B2C3D4',
};

describe('createStubFeedbackSink', () => {
  it('resolves and hands the submission to the recorder', async () => {
    const recorded = vi.fn();
    const sink = createStubFeedbackSink(recorded);

    await expect(sink.submit(submission)).resolves.toBeUndefined();
    expect(recorded).toHaveBeenCalledWith(submission);
  });

  it('works without a recorder', async () => {
    await expect(createStubFeedbackSink().submit(submission)).resolves.toBeUndefined();
  });
});
