import { useRef, useState } from 'react';
import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import { toV1Submission } from '@/domain/feedback/feedback.mapper';
import type { FeedbackAnswers } from '@/domain/feedback/feedbackForm.types';
import { sessionIdOf } from '@/domain/feedback/feedbackOrigin';
import type { FeedbackStatus } from './feedback.state';
import type { ResolvedFeedbackForm } from './useFeedbackForm';

interface SubmissionState {
  status: FeedbackStatus;
  reasonKey: string | null;
  retryable: boolean;
}

const IDLE: SubmissionState = { status: 'idle', reasonKey: null, retryable: true };
const SUBMITTING: SubmissionState = { ...IDLE, status: 'submitting' };
const SUBMITTED: SubmissionState = { ...IDLE, status: 'submitted' };

export function useFeedbackSubmission(form: ResolvedFeedbackForm) {
  const { feedback } = useServices();
  const [state, setState] = useState(IDLE);

  // A result belonging to a closed sheet is discarded, whichever way it went.
  //
  // Keeping a late success looks kinder -- the row is stored, so confirming it
  // would stop the user resubmitting -- but it cannot be done reliably here.
  // The reset is deferred 300ms for the exit animation, so a response landing
  // inside that window is wiped anyway and one landing after it is kept: the
  // same action would produce two different screens depending on network
  // timing. Worse, the kept state outlives its sheet, so the next open --
  // possibly from another screen entirely -- greets the user with a thank-you
  // for feedback they gave minutes ago, with no form to fill in.
  //
  // Deterministic and slightly less kind beats kind and unpredictable.
  const attempt = useRef(0);

  const submit = async (answers: FeedbackAnswers) => {
    const current = attempt.current;
    setState(SUBMITTING);

    try {
      await feedback.submit(toV1Submission(answers, sessionIdOf(form.origin)));
      if (attempt.current !== current) return;
      setState(SUBMITTED);
    } catch (error) {
      if (attempt.current !== current) return;
      // Nothing is reset: the entered values are the whole point of the retry.
      setState({
        status: 'failed',
        reasonKey: error instanceof AppError ? error.userMessageKey : 'errors.unknown',
        retryable: !(error instanceof AppError) || error.retryable,
      });
    }
  };

  return {
    ...state,
    submit,
    /** Drops whatever the request in flight resolves to. */
    discard: () => {
      attempt.current += 1;
    },
    reset: () => setState(IDLE),
  };
}
