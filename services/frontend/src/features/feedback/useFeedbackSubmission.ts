import { useRef, useState } from 'react';
import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import { answeredOnly } from '@/domain/feedback/feedback.mapper';
import type { FeedbackSubmission } from '@/domain/feedback/feedback.types';
import type { FeedbackAnswers } from '@/domain/feedback/feedbackForm.types';
import { audienceOf, sessionIdOf } from '@/domain/feedback/feedbackOrigin';
import type { FeedbackStatus } from './feedback.state';
import type { ResolvedFeedbackForm } from './resolveFeedbackForm';

interface SubmissionState {
  status: FeedbackStatus;
  reasonKey: string | null;
  retryable: boolean;
  /** The gateway found the answers no longer fit the current form; a reload is offered. */
  formChanged: boolean;
}

const IDLE: SubmissionState = {
  status: 'idle',
  reasonKey: null,
  retryable: true,
  formChanged: false,
};

const SUBMITTING: SubmissionState = { ...IDLE, status: 'submitting' };
const SUBMITTED: SubmissionState = { ...IDLE, status: 'submitted' };

const FORM_CHANGED = 'feedback_form_changed';

function failure(error: unknown): SubmissionState {
  if (!(error instanceof AppError)) {
    return { status: 'failed', reasonKey: 'errors.unknown', retryable: true, formChanged: false };
  }
  const formChanged = error.serverCode === FORM_CHANGED;
  return {
    status: 'failed',
    reasonKey: formChanged ? 'feedback.formChanged' : error.userMessageKey,
    retryable: error.retryable,
    formChanged,
  };
}

function toSubmission(form: ResolvedFeedbackForm, answers: FeedbackAnswers): FeedbackSubmission {
  return {
    audience: audienceOf(form.origin),
    sessionId: sessionIdOf(form.origin),
    locale: form.locale,
    formSource: form.formSource,
    revision: form.revision,
    answers: answeredOnly(form.definition.questions, answers),
  };
}

export function useFeedbackSubmission(form: ResolvedFeedbackForm | null) {
  const { feedback } = useServices();
  const [state, setState] = useState(IDLE);

  // A result belonging to a closed sheet is discarded, whichever way it went.
  //
  // Keeping a late success looks kinder -- the row is stored, so confirming it
  // would stop the user resubmitting -- but the kept state outlives its sheet,
  // so the next open -- possibly from another screen entirely -- would greet
  // the user with a thank-you for feedback they gave minutes ago, with no form
  // to fill in, or not, depending on network timing.
  //
  // Deterministic and slightly less kind beats kind and unpredictable.
  const attempt = useRef(0);

  const submit = async (answers: FeedbackAnswers) => {
    if (form === null) return;
    const current = attempt.current;
    setState(SUBMITTING);

    try {
      await feedback.submit(toSubmission(form, answers));
      if (attempt.current !== current) return;
      setState(SUBMITTED);
    } catch (error) {
      if (attempt.current !== current) return;
      // Nothing is reset: the entered values are the whole point of the retry.
      setState(failure(error));
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
