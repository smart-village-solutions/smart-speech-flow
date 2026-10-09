import type { FeedbackAnswers, FeedbackQuestion } from './feedbackForm.types';

/**
 * The answers the gateway should see: one per question the form asks, text
 * trimmed, and nothing for a question left unanswered or answered with blanks.
 */
export function answeredOnly(
  questions: readonly FeedbackQuestion[],
  answers: FeedbackAnswers
): Record<string, number | string> {
  const answered: Record<string, number | string> = {};
  for (const { id } of questions) {
    const value = answers[id];
    const kept = typeof value === 'string' ? value.trim() : value;
    if (kept !== undefined && kept !== null && kept !== '') answered[id] = kept;
  }
  return answered;
}
