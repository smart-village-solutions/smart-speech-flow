/**
 * The Gateway rejects anything longer (MAX_IMPROVEMENTS_LENGTH in
 * services/api_gateway/feedback/models.py). Without the same limit on the
 * field, a longer note is accepted by the form and refused by the server, and
 * the only way out offered is a Retry that can never succeed.
 */
export const MAX_IMPROVEMENTS_LENGTH = 4000;

export interface FeedbackFormValues {
  quality: number;
  performance: number;
  usability: number;
  nps: number;
  improvements: string;
}

/** `nps: -1` rather than 0, because 0 is a real score on an 0-10 scale. */
export const EMPTY_FORM: FeedbackFormValues = {
  quality: 0,
  performance: 0,
  usability: 0,
  nps: -1,
  improvements: '',
};

/**
 * `idle → submitting → submitted | failed`, and `failed → submitting` on retry.
 * `submitted` is reached only once the sink has resolved: thanking someone for
 * a submission the gateway rejected is the failure #303 exists to prevent.
 */
export type FeedbackStatus = 'idle' | 'submitting' | 'submitted' | 'failed';

/** Export 140: three stars set and a score chosen. The free text is optional. */
export function isComplete(values: FeedbackFormValues): boolean {
  return values.quality > 0 && values.performance > 0 && values.usability > 0 && values.nps >= 0;
}
