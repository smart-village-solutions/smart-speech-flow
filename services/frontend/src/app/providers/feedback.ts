import { createContext, useContext } from 'react';

export interface FeedbackContextValue {
  /**
   * The provider renders above <Routes>, so it cannot read the session from
   * the URL. Callers pass what they hold; the admin dashboard holds nothing.
   */
  openFeedback: (sessionId: string | null) => void;
}

export const FeedbackContext = createContext<FeedbackContextValue | null>(null);

export function useFeedback(): FeedbackContextValue {
  const value = useContext(FeedbackContext);

  if (value === null) {
    throw new Error('useFeedback must be used inside a FeedbackProvider');
  }

  return value;
}
