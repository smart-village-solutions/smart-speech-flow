import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import { QrCode } from '@/ui/patterns/QrCode';
import { useCopyToClipboard } from '@/ui/hooks/useCopyToClipboard';
import type { CopyState } from '@/ui/hooks/useCopyToClipboard';

const LABEL: Record<CopyState, string> = {
  idle: 'admin.invite.copyLink',
  copied: 'admin.invite.copied',
  failed: 'admin.invite.copyFailed',
};

interface InviteShareRowProps {
  /** The gateway's `client_url`, shown and copied exactly as received. */
  url: string;
}

export function InviteShareRow({ url }: Readonly<InviteShareRowProps>) {
  const { t } = useTranslation();
  const { state, copy } = useCopyToClipboard();

  return (
    <div className="flex w-full items-stretch gap-3">
      <button
        type="button"
        onClick={() => void copy(url)}
        className={cn(
          'flex flex-1 flex-col justify-center gap-2 rounded-2xl border p-4 text-start transition-all duration-150',
          state === 'copied'
            ? 'border-accent bg-accent-10 text-accent'
            : 'border-border-card bg-surface-card text-fg-muted'
        )}
      >
        <span className="text-caption font-semibold uppercase tracking-widest">
          {t(LABEL[state])}
        </span>
        <span className="break-all text-meta leading-snug">{url}</span>
      </button>

      <div className="flex shrink-0 flex-col items-center justify-center gap-2 rounded-2xl border border-border-card bg-surface-card p-4">
        <span className="text-caption font-semibold uppercase tracking-widest text-fg-muted">
          {t('admin.invite.qr')}
        </span>
        <QrCode value={url} title={t('admin.invite.qrTitle')} />
      </div>
    </div>
  );
}
