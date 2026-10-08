import type { FeedbackAnswers } from './feedbackForm.types';
import type { FeedbackSubmission } from './feedback.types';

/**
 * The bundled form answers by Studio's question ids; the v1 body names its
 * fields. This is the one place the two meet, until PR 13 sends answers by id.
 */
export function toV1Submission(
  answers: FeedbackAnswers,
  sessionId: string | null
): FeedbackSubmission {
  const note = answers.improvementIdeas;

  return {
    translationQuality: score(answers, 'translationQuality'),
    performance: score(answers, 'performance'),
    usability: score(answers, 'usability'),
    netPromoterScore: score(answers, 'recommendation'),
    improvements: typeof note === 'string' ? note : '',
    sessionId,
  };
}

/** The message names the question, never the answer. */
function score(answers: FeedbackAnswers, id: string): number {
  const value = answers[id];
  if (typeof value !== 'number') {
    throw new TypeError(`Feedback answer "${id}" is not a number`);
  }
  return value;
}
