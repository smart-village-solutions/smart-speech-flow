/**
 * Studio's ids for the bundled form's questions, so the fallback and a Studio
 * form answer under the same ids. The gateway's bundled form checks the same
 * ids (tests/fixtures/feedback/bundled_form.json).
 */
export const BUNDLED_QUESTION_IDS = {
  translationQuality: 'translationQuality',
  performance: 'performance',
  usability: 'usability',
  recommendation: 'recommendation',
  improvementIdeas: 'improvementIdeas',
} as const;
