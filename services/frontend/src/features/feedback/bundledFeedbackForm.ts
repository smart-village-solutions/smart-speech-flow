import type { TFunction } from 'i18next';
import type {
  FeedbackFormDefinition,
  FeedbackQuestion,
} from '@/domain/feedback/feedbackForm.types';
import { MAX_IMPROVEMENTS_LENGTH } from './feedback.state';

/** Article 13 information, on screen wherever the submit action is. */
const NOTICE_LINES = ['purpose', 'retention', 'withdrawal'] as const;

/**
 * Today's form as a definition. The ids are Studio's, so this fallback and a
 * Studio form answer the same questions.
 */
export function bundledFeedbackForm(t: TFunction): FeedbackFormDefinition {
  const rating = (id: string, key: string): FeedbackQuestion => ({
    id,
    type: 'rating',
    headline: t(`feedback.${key}.label`),
    question: t(`feedback.${key}.question`),
    required: true,
    min: 1,
    max: 5,
  });

  return {
    headline: t('feedback.title'),
    questions: [
      rating('translationQuality', 'quality'),
      rating('performance', 'performance'),
      rating('usability', 'usability'),
      {
        id: 'recommendation',
        type: 'scale',
        headline: t('feedback.nps.label'),
        question: t('feedback.nps.question'),
        required: true,
        min: 0,
        max: 10,
        minLabel: t('feedback.nps.low'),
        maxLabel: t('feedback.nps.high'),
      },
      {
        id: 'improvementIdeas',
        type: 'longText',
        headline: t('feedback.improvements.label'),
        question: t('feedback.improvements.question'),
        required: false,
        placeholder: t('feedback.improvements.placeholder'),
        maxLength: MAX_IMPROVEMENTS_LENGTH,
      },
    ],
    notice: {
      kind: 'lines',
      lines: NOTICE_LINES.map((line) => ({ id: line, text: t(`feedback.notice.${line}`) })),
    },
    button: t('feedback.submit'),
  };
}
