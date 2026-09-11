import { useCallback, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { FeedbackSheet } from '@/features/feedback/FeedbackSheet';
import { FeedbackContext } from './feedback';

export function FeedbackProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [session, setSession] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const openFeedback = useCallback((sessionId: string | null) => {
    setSession(sessionId);
    setOpen(true);
  }, []);

  const value = useMemo(() => ({ openFeedback }), [openFeedback]);

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <FeedbackSheet open={open} onOpenChange={setOpen} sessionId={session} />
    </FeedbackContext.Provider>
  );
}
