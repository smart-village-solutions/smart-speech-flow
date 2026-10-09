import * as Dialog from '@radix-ui/react-dialog';
import { Lightbulb, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import { cn } from '@/lib/cn';
import { IconButton } from '@/ui/primitives/IconButton';
import { FeedbackForm } from './FeedbackForm';
import { FeedbackSkeleton } from './FeedbackSkeleton';
import { FeedbackThanks } from './FeedbackThanks';
import { useFeedbackSheet } from './useFeedbackSheet';

const PUBLIC: FeedbackOrigin = { kind: 'public' };

interface FeedbackSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  origin?: FeedbackOrigin;
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
  origin = PUBLIC,
}: Readonly<FeedbackSheetProps>) {
  const { t } = useTranslation();
  const { form, answers, submission, close, edit, submit, reload } = useFeedbackSheet(
    origin,
    open,
    onOpenChange
  );

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
                {form?.definition.headline ?? t('feedback.title')}
              </Dialog.Title>
            </div>
            <IconButton label={t('feedback.close')} tone="close" onClick={close}>
              <X size={16} strokeWidth={2} />
            </IconButton>
          </div>

          <div className="mx-5 border-t border-border-divider" />

          {form === null && <FeedbackSkeleton label={t('feedback.loading')} />}
          {form !== null && submission.status === 'submitted' && <FeedbackThanks onClose={close} />}
          {form !== null && submission.status !== 'submitted' && (
            <FeedbackForm
              definition={form.definition}
              answers={answers}
              onChange={edit}
              onSubmit={() => void submit()}
              status={submission.status}
              reasonKey={submission.reasonKey}
              retryable={submission.retryable}
              onReload={reload}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
