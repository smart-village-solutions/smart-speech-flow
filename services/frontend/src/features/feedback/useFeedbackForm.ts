import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import type { FeedbackFormDefinition } from '@/domain/feedback/feedbackForm.types';
import { bundledFeedbackForm } from './bundledFeedbackForm';

export interface ResolvedFeedbackForm {
  origin: FeedbackOrigin;
  definition: FeedbackFormDefinition;
}

/**
 * The form a sheet opened from `origin` shows. Every origin gets the bundled
 * form until PR 13 reads Studio's public, guest and staff forms from content.
 */
export function useFeedbackForm(origin: FeedbackOrigin): ResolvedFeedbackForm {
  const { t } = useTranslation();
  return useMemo(() => ({ origin, definition: bundledFeedbackForm(t) }), [origin, t]);
}
