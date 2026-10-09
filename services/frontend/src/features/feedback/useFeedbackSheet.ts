import { useState } from 'react';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import type { FeedbackAnswers } from '@/domain/feedback/feedbackForm.types';
import { keepFitting } from './feedback.state';
import { useFeedbackSubmission } from './useFeedbackSubmission';
import { useOpenFeedbackForm } from './useOpenFeedbackForm';

export function useFeedbackSheet(
  origin: FeedbackOrigin,
  open: boolean,
  onOpenChange: (open: boolean) => void
) {
  const { form, release, reload } = useOpenFeedbackForm(origin, open);
  const submission = useFeedbackSubmission(form);
  const [entered, setEntered] = useState<FeedbackAnswers>({});
  const [wasOpen, setWasOpen] = useState(open);
  // Only what the frozen form can show is shown and sent.
  const answers = form ? keepFitting(form.definition, entered) : entered;

  // Reset on opening, not on a timer after closing: the exit transition keeps
  // showing the old form, and no late reset can wipe a sheet reopened in the
  // meantime, possibly for another origin.
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setEntered({});
      release();
      submission.reset();
    }
  }

  const close = () => {
    submission.discard();
    onOpenChange(false);
  };

  // A refusal is a verdict on the payload that was sent, so it must not
  // outlive an edit. Without this the sheet has a dead end: a submission
  // refused as terminal leaves the button disabled for the life of the sheet,
  // and the only way out is Close, which discards every rating entered. A
  // changed form is the exception: no edit makes the old form fit, and the
  // reload it offers is the way out.
  const edit = (next: FeedbackAnswers) => {
    setEntered(next);
    if (submission.status === 'failed' && !submission.formChanged) {
      submission.reset();
    }
  };

  return {
    form,
    answers,
    submission,
    close,
    edit,
    submit: () => submission.submit(answers),
    /** Only after a 409: the current form, with the answers it still accepts. */
    reload: submission.formChanged
      ? () => {
          submission.reset();
          void reload();
        }
      : undefined,
  };
}
