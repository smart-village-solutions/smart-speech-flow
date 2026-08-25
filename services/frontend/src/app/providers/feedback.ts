import { createContext, useContext } from 'react';

export interface FeedbackContextValue {
  openFeedback: () => void;
}

export const FeedbackContext = createContext<FeedbackContextValue | null>(null);

export function useFeedback(): FeedbackContextValue {
  const value = useContext(FeedbackContext);

  if (value === null) {
    throw new Error('useFeedback must be used inside a FeedbackProvider');
  }

  return value;
}
