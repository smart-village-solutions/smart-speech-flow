import { describe, expect, it } from 'vitest';
import { conversationOffsets } from '@/features/conversation/conversationOffsets';

const LEGAL_BASE = 'max(var(--spacing-legal-bottom), env(safe-area-inset-bottom))';

describe('conversationOffsets', () => {
  it('puts the legal row on the safe-area baseline and the buttons at least one legal band above it', () => {
    const band = 'max(var(--spacing-legal-band), 20px + var(--spacing-legal-gap))';

    expect(
      conversationOffsets({ keyboardOffset: 0, composerLift: '0px', legalHeight: 20 })
    ).toEqual({
      showsLegal: true,
      legalBand: band,
      legalBottom: `calc(0px + ${LEGAL_BASE})`,
      bottom: `calc(0px + ${LEGAL_BASE} + ${band} + 0px)`,
    });
  });

  it('raises the buttons over a legal row that wrapped taller than the band', () => {
    const { bottom, legalBand } = conversationOffsets({
      keyboardOffset: 0,
      composerLift: 'var(--spacing-composer-lift)',
      legalHeight: 71,
    });

    expect(legalBand).toBe('max(var(--spacing-legal-band), 71px + var(--spacing-legal-gap))');
    expect(bottom).toBe(`calc(0px + ${LEGAL_BASE} + ${legalBand} + var(--spacing-composer-lift))`);
  });

  it('hides the legal row while the keyboard is open and keeps the buttons where they always sat', () => {
    expect(
      conversationOffsets({ keyboardOffset: 300, composerLift: '0px', legalHeight: 20 })
    ).toEqual({
      showsLegal: false,
      legalBand: '0px',
      legalBottom: `calc(300px + ${LEGAL_BASE})`,
      bottom: 'calc(300px + max(var(--spacing-mic-bottom), env(safe-area-inset-bottom)) + 0px)',
    });
  });
});
