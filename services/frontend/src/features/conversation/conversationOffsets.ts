/**
 * Where the two bottom rows sit (SCREEN_SPECS conversation "Layout"): the legal
 * row on the safe-area baseline, the buttons one legal band above it, and both
 * above the software keyboard. Only the buttons take the admin's composer lift.
 */
export function conversationOffsets(
  keyboardOffset: number,
  composerLift: string
): { legalBottom: string; bottom: string } {
  const baseline = `${keyboardOffset}px + max(var(--spacing-legal-bottom), env(safe-area-inset-bottom))`;
  return {
    legalBottom: `calc(${baseline})`,
    bottom: `calc(${baseline} + var(--spacing-legal-band) + ${composerLift})`,
  };
}
