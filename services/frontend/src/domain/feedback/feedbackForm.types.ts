/**
 * A feedback form as data, so the bundled form and the forms Studio publishes
 * share one renderer. Mirrors Studio's FeedbackForm JSON except `noticeHtml`,
 * which arrives as the `html` notice variant.
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

/** Bundled copy is plain catalogue lines; Studio's `noticeHtml` is rendered through RichText. */
type FeedbackNotice =
  | { kind: 'lines'; lines: readonly { id: string; text: string }[] }
  | { kind: 'html'; html: string };

export interface FeedbackFormDefinition {
  headline: string;
  questions: readonly FeedbackQuestion[];
  notice: FeedbackNotice;
  button: string;
}

/** Keyed by question id. A missing key and null both mean unanswered. */
export type FeedbackAnswers = Record<string, number | string | null>;
