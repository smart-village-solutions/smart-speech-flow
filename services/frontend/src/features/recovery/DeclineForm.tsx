import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';

interface DeclineFormProps {
  pending: boolean;
  onDecline: (reason: string) => void;
}

/** A decline needs a reason; it does not stop the other custodians. */
export function DeclineForm({ pending, onDecline }: Readonly<DeclineFormProps>) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  if (!open) {
    return (
      <Button variant="compact" className="self-start" onClick={() => setOpen(true)}>
        {t('admin.recovery.decline.action')}
      </Button>
    );
  }
  return (
    <label className="flex flex-col gap-1.5 text-meta font-medium text-fg-muted">
      {t('admin.recovery.decline.reason')}
      <textarea
        rows={3}
        maxLength={1000}
        className="w-full rounded-xl border border-border-card bg-surface-card px-3 py-2.5 text-body text-fg-body"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <Button
        variant="compact"
        className="self-start"
        disabled={pending || reason.trim() === ''}
        onClick={() => onDecline(reason.trim())}
      >
        {t('admin.recovery.decline.submit')}
      </Button>
    </label>
  );
}
