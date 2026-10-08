/** Integers from `min` to `max`, both included. */
export function range(min: number, max: number): number[] {
  return Array.from({ length: Math.max(0, max - min + 1) }, (_, offset) => min + offset);
}
