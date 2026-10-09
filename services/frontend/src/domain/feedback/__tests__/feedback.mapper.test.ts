import { describe, expect, it } from 'vitest';
import { answeredOnly } from '@/domain/feedback/feedback.mapper';
import type { FeedbackQuestion } from '@/domain/feedback/feedbackForm.types';

const QUESTIONS: FeedbackQuestion[] = [
  { id: 'translationQuality', type: 'rating', question: 'Q', required: true, min: 1, max: 5 },
  { id: 'recommendation', type: 'scale', question: 'Q', required: true, min: 0, max: 10 },
  { id: 'improvementIdeas', type: 'longText', question: 'Q', required: false, maxLength: 4000 },
];

describe('answeredOnly', () => {
  it('keeps numbers, zero included, and trims text', () => {
    expect(
      answeredOnly(QUESTIONS, {
        translationQuality: 4,
        recommendation: 0,
        improvementIdeas: '  more languages ',
      })
    ).toEqual({ translationQuality: 4, recommendation: 0, improvementIdeas: 'more languages' });
  });

  it.each([null, '', '   '])('leaves out an unanswered question (%j)', (value) => {
    expect(answeredOnly(QUESTIONS, { translationQuality: 4, improvementIdeas: value })).toEqual({
      translationQuality: 4,
    });
  });

  it('leaves out answers to questions the form does not ask', () => {
    // The gateway refuses an unknown id with 409, as if the form had changed.
    expect(answeredOnly(QUESTIONS, { translationQuality: 4, usability: 3 })).toEqual({
      translationQuality: 4,
    });
  });
});
