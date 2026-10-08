/**
 * A feedback form as data, so the bundled form and the forms Studio publishes
 * share one renderer. Mirrors Studio's FeedbackForm JSON except `noticeHtml`,
 * which arrives as a `notice` variant in PR 13.
 */
interface QuestionBase {
  id: string;
  headline?: string;
  question: string;
  required: boolean;
}

interface RatingQuestion extends QuestionBase {
  type: 'rating';
  /** At least 1: zero stars cannot be told apart from no answer. */
  min: number;
  max: number;
}

interface ScaleQuestion extends QuestionBase {
  type: 'scale';
  min: number;
  max: number;
  minLabel?: string;
  maxLabel?: string;
}

interface LongTextQuestion extends QuestionBase {
  type: 'longText';
  placeholder?: string;
  maxLength: number;
}

export type FeedbackQuestion = RatingQuestion | ScaleQuestion | LongTextQuestion;

/**
 * Bundled copy is plain catalogue lines. PR 13 adds `{ kind: 'html'; html }`
 * for Studio's `noticeHtml`, rendered through RichText.
 */
interface FeedbackNotice {
  kind: 'lines';
  lines: readonly { id: string; text: string }[];
}

export interface FeedbackFormDefinition {
  headline: string;
  questions: readonly FeedbackQuestion[];
  notice: FeedbackNotice;
  button: string;
}

/** Keyed by question id. A missing key and null both mean unanswered. */
export type FeedbackAnswers = Record<string, number | string | null>;
