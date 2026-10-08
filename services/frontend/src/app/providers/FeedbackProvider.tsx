import { useCallback, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import { FeedbackSheet } from '@/features/feedback/FeedbackSheet';
import { FeedbackContext } from './feedback';

export function FeedbackProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [origin, setOrigin] = useState<FeedbackOrigin>({ kind: 'public' });
  const [open, setOpen] = useState(false);

  const openFeedback = useCallback((next: FeedbackOrigin) => {
    setOrigin(next);
    setOpen(true);
  }, []);

  const value = useMemo(() => ({ openFeedback }), [openFeedback]);

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <FeedbackSheet open={open} onOpenChange={setOpen} origin={origin} />
    </FeedbackContext.Provider>
  );
}
