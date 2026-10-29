import { useTranslation } from 'react-i18next';
import type { RequestStatus } from '@/domain/recovery/requests.types';

export function Chip({
  label,
  tone = 'status',
}: Readonly<{ label: string; tone?: 'status' | 'muted' | 'alert' }>) {
  const color = { status: 'text-fg-status', muted: 'text-fg-muted', alert: 'text-fg-status-alert' }[
    tone
  ];
  return (
    <span className={`rounded-full bg-surface-status px-2 py-0.5 text-meta font-medium ${color}`}>
      {label}
    </span>
  );
}

export function StatusChip({ status }: Readonly<{ status: RequestStatus }>) {
  const { t } = useTranslation();
  const tone = status === 'open' || status === 'completed' ? 'status' : 'muted';
  return <Chip label={t(`admin.recovery.status.${status}`)} tone={tone} />;
}
