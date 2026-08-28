import * as Dialog from '@radix-ui/react-dialog';
import { Button } from '@/ui/primitives/Button';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel: string;
  /** Shown inside the panel when the confirmed action failed. */
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * A modal question with exactly two answers. Every route out that is not the
 * confirming button — the cancel button, Escape, a click on the scrim — calls
 * `onCancel`, so a dismissed dialog can never be mistaken for a yes.
 *
 * Radix's `Dialog` rather than `AlertDialog`: the feedback sheet already uses
 * it, the only thing `AlertDialog` adds here is a default-focused action, and
 * the confirming action is the one that must not be default-focused.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel,
  error = null,
  onConfirm,
  onCancel,
}: Readonly<ConfirmDialogProps>) {
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
        <Dialog.Content className="fixed inset-x-5 top-1/2 z-50 mx-auto max-w-dialog -translate-y-1/2 rounded-2xl border border-border-card bg-surface-card p-5">
          <Dialog.Title className="text-thanks font-semibold text-fg-strong">{title}</Dialog.Title>
          <Dialog.Description className="mt-2 text-note leading-chat text-fg-muted">
            {body}
          </Dialog.Description>

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
            <Button variant="sheet" onClick={onConfirm} className="bg-accent text-accent-on">
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
