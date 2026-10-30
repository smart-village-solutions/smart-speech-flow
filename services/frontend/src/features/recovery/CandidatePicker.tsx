import { useTranslation } from 'react-i18next';
import type { RecoveryCandidate } from '@/domain/recovery/requests.types';
import { formatDate, formatTimeRange } from '@/features/archive/format';
import { Chip } from './StatusChip';

export const MAX_CONVERSATIONS = 50;

interface CandidatePickerProps {
  candidates: readonly RecoveryCandidate[];
  ticked: ReadonlySet<string>;
  onToggle: (conversationId: string) => void;
}

/** Clear metadata only; the conversations stay closed until the request completes (§9.5). */
export function CandidatePicker({ candidates, ticked, onToggle }: Readonly<CandidatePickerProps>) {
  const { t, i18n } = useTranslation();
  if (candidates.length === 0)
    return <p className="text-note text-fg-muted">{t('admin.recovery.new.none')}</p>;
  const full = ticked.size >= MAX_CONVERSATIONS;
  return (
    <>
      <ul className="divide-y divide-border-divider overflow-hidden rounded-2xl border border-border-card bg-surface-card">
        {candidates.map((c) => (
          <li key={c.conversationId}>
            <label className="flex w-full items-center gap-3 px-4 py-3">
              <input
                type="checkbox"
                checked={ticked.has(c.conversationId)}
                disabled={full && !ticked.has(c.conversationId)}
                onChange={() => onToggle(c.conversationId)}
              />
              <span className="flex flex-1 flex-col">
                <span className="text-note font-semibold text-fg-strong">
                  {formatDate(c.startedAt, i18n.language)}
                </span>
                <span className="text-label text-fg-muted">
                  {formatTimeRange(c.startedAt, c.endedAt, i18n.language)}
                </span>
              </span>
              {c.incomplete && <Chip label={t('admin.archive.incomplete')} tone="alert" />}
              {c.legalHold && <Chip label={t('admin.archive.hold')} />}
            </label>
          </li>
        ))}
      </ul>
      <p className="text-label text-fg-muted">{t('admin.recovery.new.limit')}</p>
    </>
  );
}
