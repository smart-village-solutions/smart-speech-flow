import { useTranslation } from 'react-i18next';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { useCandidates } from './useStartCeremony';

interface CandidateListProps {
  chosen: string[];
  onChange: (chosen: string[]) => void;
}

/** Studio's custodians; one without personal keys cannot hold a share yet. */
export function CandidateList({ chosen, onChange }: Readonly<CandidateListProps>) {
  const { t } = useTranslation();
  const candidates = useCandidates();

  if (candidates.isError) {
    return (
      <p role="alert" className="text-meta text-fg-status-alert">
        {t('admin.ceremony.directoryUnavailable')}
      </p>
    );
  }

  const toggle = (sub: string, on: boolean) =>
    onChange(on ? [...chosen, sub] : chosen.filter((item) => item !== sub));

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-2 text-note font-semibold text-fg-strong">{t('admin.ceremony.custodiansLabel')}</legend>
      {(candidates.data ?? []).map((candidate) =>
        candidate.fingerprintDisplay === null ? (
          <p key={candidate.sub} className="text-note text-fg-muted">
            {candidate.displayName} · {t('admin.ceremony.notEnrolled')}
          </p>
        ) : (
          <Checkbox
            key={candidate.sub}
            checked={chosen.includes(candidate.sub)}
            onCheckedChange={(on) => toggle(candidate.sub, on)}
          >
            {candidate.displayName}
          </Checkbox>
        )
      )}
    </fieldset>
  );
}
