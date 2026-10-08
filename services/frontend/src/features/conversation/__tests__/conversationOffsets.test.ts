import { describe, expect, it } from 'vitest';
import { conversationOffsets } from '@/features/conversation/conversationOffsets';

const BASE = 'max(var(--spacing-legal-bottom), env(safe-area-inset-bottom))';

describe('conversationOffsets', () => {
  it('puts the legal row on the safe-area baseline and the buttons one legal band above it', () => {
    expect(conversationOffsets(0, '0px')).toEqual({
      legalBottom: `calc(0px + ${BASE})`,
      bottom: `calc(0px + ${BASE} + var(--spacing-legal-band) + 0px)`,
    });
  });

  it('lifts both rows above the keyboard, and only the buttons by the admin lift', () => {
    expect(conversationOffsets(300, 'var(--spacing-composer-lift)')).toEqual({
      legalBottom: `calc(300px + ${BASE})`,
      bottom: `calc(300px + ${BASE} + var(--spacing-legal-band) + var(--spacing-composer-lift))`,
    });
  });
});
