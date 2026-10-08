import { useId } from 'react';
import { Asterisk } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import type { FeedbackQuestion as Question } from '@/domain/feedback/feedbackForm.types';
import { ScaleInput } from '@/ui/patterns/ScaleInput';
import { StarRating } from '@/ui/patterns/StarRating';

type Answer = number | string | null;

interface FeedbackQuestionProps {
  question: Question;
  value: Answer;
  onChange: (value: Answer) => void;
}

/**
 * The legend names the group, so the required marker stays out of it and is
 * read as the group's description. A rendered legend is not a flex item, which
 * is why it carries the section gap as its own margin.
 */
export function FeedbackQuestion({ question, value, onChange }: Readonly<FeedbackQuestionProps>) {
  const { t } = useTranslation();
  const requiredId = useId();
  const scale = question.type === 'scale';

  return (
    <fieldset aria-describedby={question.required ? requiredId : undefined}>
      <legend
        className={cn(
          'flex items-center gap-1',
          scale ? 'mb-3' : 'mb-2',
          question.headline === undefined
            ? 'text-body text-fg-strong'
            : 'text-label font-medium uppercase tracking-wider text-fg-muted'
        )}
      >
        {question.headline ?? question.question}
        {question.required && (
          <Asterisk aria-hidden size={10} strokeWidth={3} className="text-accent" />
        )}
      </legend>
      <div className={cn('flex flex-col', scale ? 'gap-3' : 'gap-2')}>
        {question.headline !== undefined && (
          <p className="text-body text-fg-strong">{question.question}</p>
        )}
        <QuestionInput question={question} value={value} onChange={onChange} />
      </div>
      {question.required && (
        <span id={requiredId} className="sr-only">
          {t('feedback.required')}
        </span>
      )}
    </fieldset>
  );
}

function QuestionInput({ question, value, onChange }: Readonly<FeedbackQuestionProps>) {
  const numeric = typeof value === 'number' ? value : null;

  switch (question.type) {
    case 'rating':
      return (
        <StarRating min={question.min} max={question.max} value={numeric} onChange={onChange} />
      );
    case 'scale':
      return (
        <ScaleInput
          min={question.min}
          max={question.max}
          value={numeric}
          onChange={onChange}
          minLabel={question.minLabel}
          maxLabel={question.maxLabel}
        />
      );
    case 'longText':
      return (
        <textarea
          rows={3}
          aria-label={question.question}
          maxLength={question.maxLength}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => onChange(event.target.value)}
          placeholder={question.placeholder}
          className="w-full resize-none rounded-xl border border-border-header bg-surface-field px-4 py-3 text-note leading-chat text-fg-body outline-none transition-colors duration-150 placeholder:text-fg-placeholder focus:border-accent-60"
        />
      );
  }
}
