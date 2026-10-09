import { Fragment } from 'react';
import { ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import type { FeedbackAnswers, FeedbackFormDefinition } from '@/domain/feedback/feedbackForm.types';
import { Button } from '@/ui/primitives/Button';
import { FeedbackError } from './FeedbackError';
import { FeedbackNotice } from './FeedbackNotice';
import { FeedbackQuestion } from './FeedbackQuestion';
import { isComplete } from './feedback.state';
import type { FeedbackStatus } from './feedback.state';

interface FeedbackFormProps {
  definition: FeedbackFormDefinition;
  answers: FeedbackAnswers;
  onChange: (answers: FeedbackAnswers) => void;
  onSubmit: () => void;
  status: FeedbackStatus;
  reasonKey: string | null;
  /** False when the server has judged this payload; a retry repeats it. */
  retryable?: boolean;
  /** Set when the form changed under the user; the failure then offers a reload. */
  onReload?: () => void;
}

export function FeedbackForm({
  definition,
  answers,
  onChange,
  onSubmit,
  status,
  reasonKey,
  retryable = true,
  onReload,
}: Readonly<FeedbackFormProps>) {
  const { t } = useTranslation();
  const busy = status === 'submitting';
  const refused = status === 'failed' && !retryable;
  const ready = isComplete(definition, answers) && !busy && !refused;

  const submitLabel = () => {
    if (busy) {
      return t('feedback.submitting');
    }
    return status === 'failed' ? t('feedback.retry') : definition.button;
  };

  return (
    <div className="flex flex-col gap-6 px-5 pb-8 pt-5">
      {definition.questions.map((question, index) => (
        <Fragment key={question.id}>
          {index > 0 && <div className="border-t border-border-divider" />}
          <FeedbackQuestion
            question={question}
            value={answers[question.id] ?? null}
            onChange={(value) => onChange({ ...answers, [question.id]: value })}
          />
        </Fragment>
      ))}

      {reasonKey !== null && (
        <FeedbackError
          reasonKey={reasonKey}
          action={onReload && { label: t('feedback.reload'), onClick: onReload }}
        />
      )}

      <FeedbackNotice notice={definition.notice} />

      <Button
        variant="sheet"
        disabled={!ready}
        aria-busy={busy}
        onClick={onSubmit}
        className={cn(ready ? 'bg-accent text-accent-on' : 'bg-surface-disabled text-fg-disabled')}
      >
        {submitLabel()}
        {ready && <ChevronRight size={16} strokeWidth={2.5} />}
      </Button>
    </div>
  );
}
