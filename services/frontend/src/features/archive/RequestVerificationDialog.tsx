import { useTranslation } from 'react-i18next';
import { QuestionDialog } from '@/ui/patterns/QuestionDialog';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { ReviewerPicker } from './ReviewerPicker';
import type { RequestVerification } from './useRequestVerification';

interface RequestVerificationDialogProps {
  request: RequestVerification;
  languages: readonly string[];
  onClose: () => void;
}

/** Pick a reviewer, compare their fingerprint, then wrap and assign (spec §10.7). */
export function RequestVerificationDialog({
  request,
  languages,
  onClose,
}: Readonly<RequestVerificationDialogProps>) {
  const { t } = useTranslation();
  const confirming = request.stage === 'confirm';
  const error =
    request.error === null ? null : t(`admin.archive.verification.error.${request.error}`);
  return (
    <QuestionDialog
      open
      title={t('admin.archive.verification.dialogTitle')}
      confirmLabel={t(
        confirming ? 'admin.archive.verification.assign' : 'admin.archive.verification.next'
      )}
      cancelLabel={t('admin.archive.verification.cancel')}
      error={error}
      confirmDisabled={request.stage === 'stepUp' || request.picked === null || request.pending}
      onConfirm={confirming ? request.submit : () => void request.next()}
      onCancel={onClose}
    >
      {request.stage === 'stepUp' && <StepUpPrompt returnTo="archive" />}
      {request.stage === 'pick' && request.candidates.isError && (
        <p role="alert" className="mt-3 text-label text-fg-status-alert">
          {t('admin.archive.verification.error.DIRECTORY_UNAVAILABLE')}
        </p>
      )}
      {request.stage === 'pick' && request.candidates.data && (
        <ReviewerPicker
          candidates={request.candidates.data}
          languages={languages}
          picked={request.picked}
          onPick={request.pick}
        />
      )}
      {confirming && request.picked && (
        <section className="mt-4 flex flex-col gap-2 rounded-2xl border border-border-status p-4">
          <p className="text-label text-fg-muted">
            {t('admin.archive.verification.fingerprint', { name: request.picked.displayName })}
          </p>
          <code className="text-body font-semibold text-fg-strong">{request.checked}</code>
          <p className="text-label text-fg-muted">
            {t('admin.archive.verification.fingerprintHint')}
          </p>
          {request.pending && (
            <p className="text-label text-fg-muted">{t('admin.archive.verification.wrapping')}</p>
          )}
        </section>
      )}
    </QuestionDialog>
  );
}
