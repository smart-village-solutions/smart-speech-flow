import { useState } from 'react';
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

  const close = () => {
    onOpenChange(false);
    window.setTimeout(() => {
      setValues(EMPTY_FORM);
      setStatus('idle');
      setReasonKey(null);
    }, 300);
  };

  const submit = async () => {
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
      setStatus('submitted');
    } catch (error) {
      // Nothing is reset: the entered values are the whole point of the retry.
      setReasonKey(error instanceof AppError ? error.userMessageKey : 'errors.unknown');
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
              onChange={setValues}
              onSubmit={() => void submit()}
              status={status}
              reasonKey={reasonKey}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
