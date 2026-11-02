import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { QuestionDialog } from '@/ui/patterns/QuestionDialog';

type Outcome = 'approved' | 'not_approved';

interface DecisionDialogProps {
  pending: boolean;
  error: string | null;
  onDecide: (outcome: Outcome) => void;
  onCancel: () => void;
}

/** The decision is signed and final; the reviewer's access ends with it (spec §10.7). */
export function DecisionDialog({
  pending,
  error,
  onDecide,
  onCancel,
}: Readonly<DecisionDialogProps>) {
  const { t } = useTranslation();
  const name = useId();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  return (
    <QuestionDialog
      open
      title={t('admin.review.decision.title')}
      confirmLabel={t('admin.review.decision.submit')}
      cancelLabel={t('admin.review.cancel')}
      error={error === null ? null : t(`admin.review.error.${error}`)}
      confirmDisabled={outcome === null || pending}
      onConfirm={() => outcome && onDecide(outcome)}
      onCancel={onCancel}
    >
      <div className="mt-4 flex flex-col gap-2">
        {(['approved', 'not_approved'] as const).map((value) => (
          <label key={value} className="flex items-center gap-2 text-note text-fg-body">
            <input
              type="radio"
              name={name}
              checked={outcome === value}
              onChange={() => setOutcome(value)}
            />
            {t(`admin.review.decision.${value}`)}
          </label>
        ))}
        <p className="text-label text-fg-muted">{t('admin.review.decision.hint')}</p>
      </div>
    </QuestionDialog>
  );
}
