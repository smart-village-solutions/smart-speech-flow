import { useTranslation } from 'react-i18next';
import type { RequestStatus } from '@/domain/recovery/requests.types';
import { StatusChip as SharedStatusChip } from '@/ui/primitives/StatusChip';

export function Chip({
  label,
  tone = 'status',
}: Readonly<{ label: string; tone?: 'status' | 'muted' | 'alert' }>) {
  return (
    <SharedStatusChip tone={tone === 'alert' ? 'danger' : 'neutral'} showIndicator={false} className={`h-auto border-0 px-2 py-0.5 text-meta ${tone === 'muted' ? 'text-fg-muted' : ''}`}>
      {label}
    </SharedStatusChip>
  );
}

export function StatusChip({ status }: Readonly<{ status: RequestStatus }>) {
  const { t } = useTranslation();
  const tone = status === 'open' || status === 'completed' ? 'status' : 'muted';
  return <Chip label={t(`admin.recovery.status.${status}`)} tone={tone} />;
}
