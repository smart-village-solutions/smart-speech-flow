import { Fragment } from 'react';
import { ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import { Button } from '@/ui/primitives/Button';
import { NpsScale } from '@/ui/patterns/NpsScale';
import { StarRating } from '@/ui/patterns/StarRating';
import { FeedbackError } from './FeedbackError';
import { isComplete, MAX_IMPROVEMENTS_LENGTH } from './feedback.state';
import type { FeedbackFormValues, FeedbackStatus } from './feedback.state';

const RATING_SECTIONS = [
  { key: 'quality', field: 'quality' },
  { key: 'performance', field: 'performance' },
  { key: 'usability', field: 'usability' },
] as const;

/** Article 13 information, on screen wherever the submit action is. */
const NOTICE_LINES = ['purpose', 'retention', 'withdrawal'] as const;

interface FeedbackFormProps {
  values: FeedbackFormValues;
  onChange: (values: FeedbackFormValues) => void;
  onSubmit: () => void;
  status: FeedbackStatus;
  reasonKey: string | null;
}

export function FeedbackForm({
  values,
  onChange,
  onSubmit,
  status,
  reasonKey,
}: Readonly<FeedbackFormProps>) {
  const { t } = useTranslation();
  const busy = status === 'submitting';
  const ready = isComplete(values) && !busy;
  const set = (patch: Partial<FeedbackFormValues>) => onChange({ ...values, ...patch });

  const submitKey = () => {
    if (busy) {
      return 'feedback.submitting';
    }
    return status === 'failed' ? 'feedback.retry' : 'feedback.submit';
  };

  return (
    <div className="flex flex-col gap-6 px-5 pb-8 pt-5">
      {RATING_SECTIONS.map((section, index) => (
        <Fragment key={section.key}>
          {index > 0 && <div className="border-t border-border-divider" />}
          <div className="flex flex-col gap-2">
            <p className="text-label font-medium uppercase tracking-wider text-fg-muted">
              {t(`feedback.${section.key}.label`)}
            </p>
            <p className="text-body text-fg-strong">{t(`feedback.${section.key}.question`)}</p>
            <StarRating
              label={t(`feedback.${section.key}.label`)}
              value={values[section.field]}
              onChange={(value) => set({ [section.field]: value })}
            />
          </div>
        </Fragment>
      ))}

      <div className="border-t border-border-divider" />

      <div className="flex flex-col gap-3">
        <p className="text-label font-medium uppercase tracking-wider text-fg-muted">
          {t('feedback.nps.label')}
        </p>
        <p className="text-body text-fg-strong">{t('feedback.nps.question')}</p>
        <NpsScale value={values.nps} onChange={(nps) => set({ nps })} />
        <div className="flex justify-between text-caption text-fg-muted">
          <span>{t('feedback.nps.low')}</span>
          <span>{t('feedback.nps.high')}</span>
        </div>
      </div>

      <div className="border-t border-border-divider" />

      <div className="flex flex-col gap-2">
        <p className="text-label font-medium uppercase tracking-wider text-fg-muted">
          {t('feedback.improvements.label')}
        </p>
        <p className="text-body text-fg-strong">{t('feedback.improvements.question')}</p>
        <textarea
          rows={3}
          maxLength={MAX_IMPROVEMENTS_LENGTH}
          value={values.improvements}
          onChange={(event) => set({ improvements: event.target.value })}
          placeholder={t('feedback.improvements.placeholder')}
          className="w-full resize-none rounded-xl border border-border-header bg-surface-field px-4 py-3 text-note leading-chat text-fg-body outline-none transition-colors duration-150 placeholder:text-fg-placeholder focus:border-accent-60"
        />
      </div>

      {reasonKey !== null && <FeedbackError reasonKey={reasonKey} />}

      <div className="flex flex-col gap-1">
        {NOTICE_LINES.map((line) => (
          <p key={line} className="text-caption leading-chat text-fg-subtle">
            {t(`feedback.notice.${line}`)}
          </p>
        ))}
      </div>

      <Button
        variant="sheet"
        disabled={!ready}
        aria-busy={busy}
        onClick={onSubmit}
        className={cn(ready ? 'bg-accent text-accent-on' : 'bg-surface-disabled text-fg-disabled')}
      >
        {t(submitKey())}
        {ready && <ChevronRight size={16} strokeWidth={2.5} />}
      </Button>
    </div>
  );
}
