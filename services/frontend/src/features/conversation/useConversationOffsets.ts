import { useRef } from 'react';
import type { ClientRole } from '@/core/roles';
import { useElementHeight } from '@/ui/hooks/useElementHeight';
import { conversationOffsets } from './conversationOffsets';
import { useKeyboardOffset } from './useKeyboardOffset';

/** The keyboard offset, the measured legal row and the bottom-row positions they give. */
export function useConversationOffsets(role: ClientRole) {
  const keyboardOffset = useKeyboardOffset();
  const legalRef = useRef<HTMLDivElement | null>(null);
  const legalHeight = useElementHeight(legalRef);

  // The admin surface carries a terminate link at the customer's composer
  // baseline, so its composer sits a step higher. Applied here rather than in
  // the surface because the send flight launches from this value.
  const composerLift = role === 'admin' ? 'var(--spacing-composer-lift)' : '0px';

  return {
    keyboardOffset,
    composerLift,
    legalRef,
    ...conversationOffsets({ keyboardOffset, composerLift, legalHeight }),
  };
}
