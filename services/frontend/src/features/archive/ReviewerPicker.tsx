import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ReviewerCandidate } from '@/domain/archive/archive.types';
import { covering } from './useRequestVerification';

interface ReviewerPickerProps {
  candidates: readonly ReviewerCandidate[];
  languages: readonly string[];
  picked: ReviewerCandidate | null;
  onPick: (candidate: ReviewerCandidate) => void;
}

/** The language filter runs here: the conversation's languages never reach the gateway. */
export function ReviewerPicker({
  candidates,
  languages,
  picked,
  onPick,
}: Readonly<ReviewerPickerProps>) {
  const { t } = useTranslation();
  const name = useId();
  const [all, setAll] = useState(false);
  const shown = all ? candidates : covering(candidates, languages);
  return (
    <div className="mt-4 flex flex-col gap-2">
      {shown.length === 0 ? (
        <p className="text-note text-fg-muted">{t('admin.archive.verification.noneMatch')}</p>
      ) : (
        <ul className="max-h-review-list divide-y divide-border-divider overflow-y-auto rounded-2xl border border-border-card">
          {shown.map((candidate) => (
            <li key={candidate.sub}>
              <label className="flex items-start gap-3 px-4 py-3">
                <input
                  type="radio"
                  name={name}
                  checked={picked?.sub === candidate.sub}
                  onChange={() => onPick(candidate)}
                  className="mt-1"
                />
                <span className="flex flex-col">
                  <span className="text-note font-semibold text-fg-strong">
                    {candidate.displayName}
                    {candidate.sworn && (
                      <span className="ms-2 rounded-full bg-surface-status px-2 py-0.5 text-meta font-medium text-fg-status">
                        {t('admin.archive.verification.sworn')}
                      </span>
                    )}
                  </span>
                  <span className="text-label text-fg-muted">{candidate.languages.join(', ')}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <label className="flex items-center gap-2 text-label text-fg-body">
        <input type="checkbox" checked={all} onChange={(event) => setAll(event.target.checked)} />
        {t('admin.archive.verification.allReviewers')}
      </label>
    </div>
  );
}
