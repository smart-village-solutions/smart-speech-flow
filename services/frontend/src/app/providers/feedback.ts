import { createContext, useContext } from 'react';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';

export interface FeedbackContextValue {
  /**
   * The provider renders above <Routes>, so it cannot read the session from
   * the URL. Callers say where they are and pass the session they hold.
   */
  openFeedback: (origin: FeedbackOrigin) => void;
}

export const FeedbackContext = createContext<FeedbackContextValue | null>(null);

export function useFeedback(): FeedbackContextValue {
  const value = useContext(FeedbackContext);

  if (value === null) {
    throw new Error('useFeedback must be used inside a FeedbackProvider');
  }

  return value;
}
