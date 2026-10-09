import { describe, expect, it } from 'vitest';
import type { FeedbackFormDefinition } from '@/domain/feedback/feedbackForm.types';
import { isComplete, keepFitting } from '@/features/feedback/feedback.state';

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

describe('keepFitting', () => {
  it('keeps every answer the form still accepts, unchanged', () => {
    const answers = { stars: 3, score: 0, note: ' short ' };

    expect(keepFitting(FORM, answers)).toEqual(answers);
  });

  it('drops answers to questions the form no longer asks', () => {
    expect(keepFitting(FORM, { stars: 3, usability: 4 })).toEqual({ stars: 3 });
  });

  it.each([
    ['a number now out of range', { stars: 9 }],
    ['text where a number is asked', { score: 'nine' }],
    ['a number where text is asked', { note: 4 }],
    ['text over the new limit', { note: 'far too long now' }],
  ])('drops %s', (_name, answers) => {
    expect(keepFitting(FORM, answers)).toEqual({});
  });

  it('keeps text still being typed, blanks included', () => {
    const required: FeedbackFormDefinition = {
      ...FORM,
      questions: [{ id: 'note', type: 'longText', question: 'Q', required: true, maxLength: 10 }],
    };

    expect(keepFitting(required, { note: '  ' })).toEqual({ note: '  ' });
  });
});
