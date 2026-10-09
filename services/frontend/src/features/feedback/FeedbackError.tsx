import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';

interface FeedbackErrorProps {
  reasonKey: string;
  /** A way out the failure itself offers, such as loading a changed form. */
  action?: { label: string; onClick: () => void };
}

/**
 * Sits above the submit action rather than replacing the form: a failed
 * submission keeps every entered value, and they stay editable while the
 * customer decides whether to retry.
 */
export function FeedbackError({ reasonKey, action }: Readonly<FeedbackErrorProps>) {
  const { t } = useTranslation();

  return (
    <div role="alert" className="flex flex-col gap-1 rounded-xl bg-surface-danger-hover px-4 py-3">
      <p className="text-label font-medium text-fg-danger">{t('feedback.failed')}</p>
      <p className="text-caption leading-chat text-fg-danger">{t(reasonKey)}</p>
      {action && (
        <Button
          variant="compact"
          onClick={action.onClick}
          className="mt-2 self-start bg-accent text-accent-on"
        >
          {action.label}
        </Button>
      )}
    </div>
  );
}
