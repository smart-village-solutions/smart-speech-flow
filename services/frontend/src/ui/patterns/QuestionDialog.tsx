import * as Dialog from '@radix-ui/react-dialog';
import type { ReactNode } from 'react';
import { Button } from '@/ui/primitives/Button';

interface QuestionDialogProps {
  open: boolean;
  title: string;
  /** Everything between the title and the buttons: text, fields, a pad. */
  children: ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  /** Shown above the buttons when the confirmed action failed or needs more. */
  error?: string | null;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * `ConfirmDialog`'s shell around a form: same panel, same two answers, and every
 * route out that is not the confirming button calls `onCancel`. The panel stops
 * short of the viewport and scrolls, so a long text never hides the buttons.
 */
export function QuestionDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel,
  error = null,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: Readonly<QuestionDialogProps>) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          onCancel();
        }
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-surface-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed inset-x-5 top-1/2 z-50 mx-auto max-h-consent-dialog max-w-dialog -translate-y-1/2 overflow-y-auto rounded-2xl border border-border-card bg-surface-card p-5 font-sans text-body"
        >
          <Dialog.Title className="text-thanks font-semibold text-fg-strong">{title}</Dialog.Title>
          {children}

          {error !== null && (
            <p role="alert" className="mt-3 text-label text-fg-status-alert">
              {error}
            </p>
          )}

          <div className="mt-5 flex gap-3">
            <Button
              variant="sheet"
              onClick={onCancel}
              className="border border-border-card text-fg-body"
            >
              {cancelLabel}
            </Button>
            <Button
              variant="sheet"
              onClick={onConfirm}
              disabled={confirmDisabled}
              className="bg-accent text-accent-on disabled:opacity-50"
            >
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
