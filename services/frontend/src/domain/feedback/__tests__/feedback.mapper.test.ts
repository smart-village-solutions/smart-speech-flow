import { describe, expect, it } from 'vitest';
import { toV1Submission } from '@/domain/feedback/feedback.mapper';

const ANSWERS = {
  translationQuality: 4,
  performance: 5,
  usability: 3,
  recommendation: 0,
  improvementIdeas: 'more languages',
};

describe('toV1Submission', () => {
  it('maps Studio question ids onto the v1 fields', () => {
    expect(toV1Submission(ANSWERS, 'A1B2C3D4')).toEqual({
      translationQuality: 4,
      performance: 5,
      usability: 3,
      netPromoterScore: 0,
      improvements: 'more languages',
      sessionId: 'A1B2C3D4',
    });
  });

  it('sends an empty note when the free text was left unanswered', () => {
    expect(toV1Submission({ ...ANSWERS, improvementIdeas: null }, null).improvements).toBe('');
  });

  it('refuses a score that was never given rather than inventing one', () => {
    expect(() => toV1Submission({ ...ANSWERS, usability: null }, null)).toThrow('usability');
  });
});
