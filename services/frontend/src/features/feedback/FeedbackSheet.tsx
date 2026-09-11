import { useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Lightbulb, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import { cn } from '@/lib/cn';
import { IconButton } from '@/ui/primitives/IconButton';
import { FeedbackForm } from './FeedbackForm';
import { FeedbackThanks } from './FeedbackThanks';
import { EMPTY_FORM } from './feedback.state';
import type { FeedbackStatus } from './feedback.state';

interface FeedbackSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessionId?: string | null;
}

/**
 * Radix owns presence here rather than forceMount: a force-mounted panel keeps
 * the modal scroll lock and aria-hidden applied to the rest of the page even
 * while closed. Radix holds the node until the exit animation finishes, so the
 * design's 300ms slide survives.
 */
export function FeedbackSheet({
  open,
  onOpenChange,
  sessionId = null,
}: Readonly<FeedbackSheetProps>) {
  const { t } = useTranslation();
  const { feedback } = useServices();
  const [values, setValues] = useState(EMPTY_FORM);
  const [status, setStatus] = useState<FeedbackStatus>('idle');
  const [reasonKey, setReasonKey] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(true);

  // A result belonging to a closed sheet is discarded, whichever way it went.
  //
  // Keeping a late success looks kinder -- the row is stored, so confirming it
  // would stop the user resubmitting -- but it cannot be done reliably here.
  // The reset below is deferred 300ms for the exit animation, so a response
  // landing inside that window is wiped anyway and one landing after it is
  // kept: the same action would produce two different screens depending on
  // network timing. Worse, the kept state outlives its sheet, so the next
  // open -- possibly from another screen entirely -- greets the user with a
  // thank-you for feedback they gave minutes ago, with no form to fill in.
  //
  // Deterministic and slightly less kind beats kind and unpredictable.
  const attempt = useRef(0);

  const close = () => {
    attempt.current += 1;
    onOpenChange(false);
    window.setTimeout(() => {
      setValues(EMPTY_FORM);
      setStatus('idle');
      setReasonKey(null);
      setRetryable(true);
    }, 300);
  };

  // A refusal is a verdict on the payload that was sent, so it must not
  // outlive an edit. Without this the sheet has a dead end: a submission
  // refused as terminal leaves the button disabled for the life of the sheet,
  // and the only way out is Close, which discards every rating entered.
  const edit = (next: typeof values) => {
    setValues(next);
    if (status === 'failed') {
      setStatus('idle');
      setReasonKey(null);
      setRetryable(true);
    }
  };

  const submit = async () => {
    const current = attempt.current;
    setStatus('submitting');
    setReasonKey(null);

    try {
      await feedback.submit({
        translationQuality: values.quality,
        performance: values.performance,
        usability: values.usability,
        netPromoterScore: values.nps,
        improvements: values.improvements,
        sessionId,
      });
      if (attempt.current !== current) return;
      setStatus('submitted');
    } catch (error) {
      if (attempt.current !== current) return;
      // Nothing is reset: the entered values are the whole point of the retry.
      setReasonKey(error instanceof AppError ? error.userMessageKey : 'errors.unknown');
      setRetryable(!(error instanceof AppError) || error.retryable);
      setStatus('failed');
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-surface-scrim data-[state=closed]:animate-scrim-out data-[state=open]:animate-scrim-in" />
        <Dialog.Content
          aria-describedby={undefined}
          className={cn(
            'fixed inset-x-0 bottom-0 z-50 max-h-[90dvh] overflow-y-auto',
            'rounded-t-sheet border-x border-t border-border-header bg-surface-panel',
            'data-[state=closed]:animate-sheet-out data-[state=open]:animate-sheet-in'
          )}
        >
          <div className="flex justify-center pb-1 pt-3">
            <div className="h-1 w-10 rounded-full bg-surface-handle" />
          </div>

          <div className="flex items-center justify-between px-5 py-4">
            <div className="flex items-center gap-2">
              <Lightbulb size={18} strokeWidth={2} className="text-accent" />
              <Dialog.Title className="text-item font-semibold text-fg-strong">
                {t('feedback.title')}
              </Dialog.Title>
            </div>
            <IconButton label={t('feedback.close')} tone="close" onClick={close}>
              <X size={16} strokeWidth={2} />
            </IconButton>
          </div>

          <div className="mx-5 border-t border-border-divider" />

          {status === 'submitted' ? (
            <FeedbackThanks onClose={close} />
          ) : (
            <FeedbackForm
              values={values}
              onChange={edit}
              onSubmit={() => void submit()}
              status={status}
              reasonKey={reasonKey}
              retryable={retryable}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
