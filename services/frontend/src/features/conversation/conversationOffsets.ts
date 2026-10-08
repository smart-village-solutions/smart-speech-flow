interface OffsetInputs {
  keyboardOffset: number;
  composerLift: string;
  /** The legal row's rendered height in px; 0 until measured. */
  legalHeight: number;
}

export interface ConversationOffsets {
  showsLegal: boolean;
  legalBottom: string;
  /** What the buttons row stands above the legal row's baseline; the chat stack gives it up. */
  legalBand: string;
  bottom: string;
}

const SAFE = 'env(safe-area-inset-bottom)';

/**
 * Where the two bottom rows sit (SCREEN_SPECS conversation "Layout"). The
 * legal row sits on the safe-area baseline and the buttons at least one legal
 * band above it, higher if the links wrapped taller (enlarged text). While the
 * keyboard is open the legal row hides and the buttons keep their old place
 * above the keyboard. Only the buttons take the admin's composer lift.
 */
export function conversationOffsets({
  keyboardOffset,
  composerLift,
  legalHeight,
}: OffsetInputs): ConversationOffsets {
  const legalBaseline = `${keyboardOffset}px + max(var(--spacing-legal-bottom), ${SAFE})`;

  if (keyboardOffset > 0) {
    return {
      showsLegal: false,
      legalBand: '0px',
      legalBottom: `calc(${legalBaseline})`,
      bottom: `calc(${keyboardOffset}px + max(var(--spacing-mic-bottom), ${SAFE}) + ${composerLift})`,
    };
  }

  const legalBand = `max(var(--spacing-legal-band), ${legalHeight}px + var(--spacing-legal-gap))`;
  return {
    showsLegal: true,
    legalBand,
    legalBottom: `calc(${legalBaseline})`,
    bottom: `calc(${legalBaseline} + ${legalBand} + ${composerLift})`,
  };
}
