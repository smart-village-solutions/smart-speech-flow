import { describe, expect, it } from 'vitest';
import type { FeedbackFormDefinition } from '@/domain/feedback/feedbackForm.types';
import { isComplete } from '@/features/feedback/feedback.state';

const FORM: FeedbackFormDefinition = {
  headline: 'Tell us',
  button: 'Send',
  notice: { kind: 'lines', lines: [] },
  questions: [
    { id: 'stars', type: 'rating', question: 'How was it?', required: true, min: 1, max: 7 },
    { id: 'score', type: 'scale', question: 'Recommend?', required: true, min: 0, max: 10 },
    { id: 'note', type: 'longText', question: 'Anything?', required: false, maxLength: 10 },
  ],
};

describe('isComplete', () => {
  it('needs every required answer', () => {
    expect(isComplete(FORM, {})).toBe(false);
    expect(isComplete(FORM, { stars: 7 })).toBe(false);
    expect(isComplete(FORM, { stars: 7, score: 5 })).toBe(true);
  });

  it('counts zero on a zero-based scale as an answer', () => {
    expect(isComplete(FORM, { stars: 1, score: 0, note: null })).toBe(true);
  });

  it.each([0, 8, 1.5])('rejects %s on a 1-7 rating', (stars) => {
    expect(isComplete(FORM, { stars, score: 5 })).toBe(false);
  });

  it('rejects text where a number belongs', () => {
    expect(isComplete(FORM, { stars: '5', score: 5 })).toBe(false);
  });

  it('measures text after trimming', () => {
    expect(isComplete(FORM, { stars: 1, score: 1, note: `  ${'x'.repeat(10)}  ` })).toBe(true);
    expect(isComplete(FORM, { stars: 1, score: 1, note: 'x'.repeat(11) })).toBe(false);
  });

  it('does not accept blank text for a required question', () => {
    const form: FeedbackFormDefinition = {
      ...FORM,
      questions: [
        { id: 'note', type: 'longText', question: 'Anything?', required: true, maxLength: 10 },
      ],
    };

    expect(isComplete(form, { note: '   ' })).toBe(false);
    expect(isComplete(form, { note: 'ok' })).toBe(true);
  });
});
