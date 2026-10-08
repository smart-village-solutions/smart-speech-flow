import type {
  FeedbackAnswers,
  FeedbackFormDefinition,
  FeedbackQuestion,
} from '@/domain/feedback/feedbackForm.types';

/**
 * The Gateway rejects anything longer (MAX_IMPROVEMENTS_LENGTH in
 * services/api_gateway/feedback/models.py). Without the same limit on the
 * field, a longer note is accepted by the form and refused by the server, and
 * the only way out offered is a Retry that can never succeed.
 */
export const MAX_IMPROVEMENTS_LENGTH = 4000;

type LongTextQuestion = Extract<FeedbackQuestion, { type: 'longText' }>;
type NumericQuestion = Exclude<FeedbackQuestion, LongTextQuestion>;

/**
 * `idle → submitting → submitted | failed`, and `failed → submitting` on retry.
 * `submitted` is reached only once the sink has resolved: thanking someone for
 * a submission the gateway rejected is the failure #303 exists to prevent.
 */
export type FeedbackStatus = 'idle' | 'submitting' | 'submitted' | 'failed';

/**
 * Every required question answered, every number within its range, every text
 * within its limit once trimmed. For the bundled form this is export 140:
 * three stars set and a score chosen, the free text optional.
 */
export function isComplete(definition: FeedbackFormDefinition, answers: FeedbackAnswers): boolean {
  return definition.questions.every((question) => fits(question, answers[question.id] ?? null));
}

function fits(question: FeedbackQuestion, value: number | string | null): boolean {
  if (value === null) {
    return !question.required;
  }
  return question.type === 'longText' ? textFits(question, value) : numberFits(question, value);
}

function textFits(question: LongTextQuestion, value: number | string): boolean {
  if (typeof value !== 'string') {
    return false;
  }
  const text = value.trim();
  return text.length <= question.maxLength && (text !== '' || !question.required);
}

function numberFits(question: NumericQuestion, value: number | string): boolean {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= question.min &&
    value <= question.max
  );
}
