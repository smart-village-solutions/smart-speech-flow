/**
 * Studio's ids for the bundled form's questions. The bundled definition asks
 * under them and the v1 mapper reads them back, so they must be one source.
 */
export const BUNDLED_QUESTION_IDS = {
  translationQuality: 'translationQuality',
  performance: 'performance',
  usability: 'usability',
  recommendation: 'recommendation',
  improvementIdeas: 'improvementIdeas',
} as const;
