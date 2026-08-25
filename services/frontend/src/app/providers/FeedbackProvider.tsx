import { useCallback, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { FeedbackSheet } from '@/features/feedback/FeedbackSheet';
import { FeedbackContext } from './feedback';

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const openFeedback = useCallback(() => setOpen(true), []);
  const value = useMemo(() => ({ openFeedback }), [openFeedback]);

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <FeedbackSheet open={open} onOpenChange={setOpen} />
    </FeedbackContext.Provider>
  );
}
