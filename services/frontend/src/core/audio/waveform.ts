/** Waveform geometry, transcribed from the Figma export (App.tsx:687-697, 712-721). */

export const BAR_COUNT = 50;
/** The export renders the first five bars as flat 4px stubs. */
export const LEAD_BARS = 5;
export const RECORDING_SECONDS = 20;

/**
 * The export generates bar heights with Math.random() at import time, so the
 * waveform differs on every page load. The shape is decorative, not data, so it
 * is generated deterministically here instead: same range (0.25 to 1), same
 * flat lead-in, but stable across renders, devices and screenshots.
 */
function barHeight(index: number): number {
  if (index < LEAD_BARS) {
    return 0;
  }

  const pseudoRandom = Math.abs(Math.sin(index * 12.9898) * 43758.5453) % 1;
  return pseudoRandom * 0.75 + 0.25;
}

export const WAVE_HEIGHTS: number[] = Array.from({ length: BAR_COUNT }, (_, index) =>
  barHeight(index)
);

/** Maps a 0-1 progress fraction onto the number of filled bars. */
export function activeBarsForProgress(fraction: number): number {
  const clamped = Math.min(1, Math.max(0, fraction));
  return Math.floor(clamped * BAR_COUNT);
}
