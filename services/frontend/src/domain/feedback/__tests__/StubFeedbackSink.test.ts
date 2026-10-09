import { describe, expect, it, vi } from 'vitest';
import { createStubFeedbackSink } from '@/domain/feedback/StubFeedbackSink';
import type { FeedbackSubmission } from '@/domain/feedback/feedback.types';

const submission: FeedbackSubmission = {
  audience: 'guest',
  sessionId: 'A1B2C3D4',
  locale: 'en',
  formSource: 'bundled',
  revision: null,
  answers: { translationQuality: 5, improvementIdeas: 'more languages' },
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
