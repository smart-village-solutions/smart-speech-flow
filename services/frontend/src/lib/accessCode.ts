/** Gateway session ids are uuid4()[:8].upper() — eight characters. */
export const CODE_LENGTH = 8;

/**
 * The code travels as a fixed-length string in which a space marks an empty
 * position. Without that padding, clearing an interior box would pull every
 * later character one place to the left. Callers strip the spaces first.
 */
export function normalizeCode(value: string): string {
  return value.replace(/ /g, '');
}
