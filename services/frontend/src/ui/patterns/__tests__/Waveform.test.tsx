import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Waveform } from '@/ui/patterns/Waveform';
import { BAR_COUNT, WAVE_HEIGHTS } from '@/core/audio/waveform';

/** Every slot in the row, drawn or not — the row is always BAR_COUNT wide. */
function slots(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>('[aria-hidden="true"] > div')];
}

/** Only the slots carrying a bar; an empty slot just holds its width open. */
function barHeights(container: HTMLElement): string[] {
  return slots(container)
    .filter((slot) => slot.style.height !== '')
    .map((slot) => slot.style.height);
}

describe('Waveform', () => {
  it('draws the decorative shape when given no heights', () => {
    const { container } = render(<Waveform activeBars={0} barColorClass="bg-accent" />);

    expect(barHeights(container)).toHaveLength(BAR_COUNT);
    // The export's flat 4px lead-in.
    expect(barHeights(container)[0]).toBe('4px');
  });

  // With bars sharing the row by flex, a part-recorded waveform would stretch
  // to full width and shrink as it filled: three bars would read as one flat
  // line across the bubble. The row always holds BAR_COUNT slots instead, so a
  // bar is the same width at one second as at twenty.
  it('keeps a partial waveform to its own width, leaving the rest of the row empty', () => {
    const { container } = render(
      <Waveform activeBars={3} barColorClass="bg-accent" heights={[1, 0.5, 0.25]} />
    );

    expect(slots(container)).toHaveLength(BAR_COUNT);
    expect(barHeights(container)).toEqual(['100%', '50%', '25%']);
  });

  it('paints nothing in a slot that holds no bar', () => {
    const { container } = render(
      <Waveform activeBars={1} barColorClass="bg-accent" heights={[1]} />
    );

    const empty = slots(container).slice(1);
    expect(empty.every((slot) => slot.className.includes('bg-'))).toBe(false);
  });

  it('draws the heights it is given, so real audio can drive it', () => {
    const { container } = render(
      <Waveform activeBars={0} barColorClass="bg-accent" heights={[1, 0.5, 0.25]} />
    );

    expect(barHeights(container)).toEqual(['100%', '50%', '25%']);
  });

  it('has no flat lead-in for real audio, which has no such thing', () => {
    const real = new Array(BAR_COUNT).fill(0.4);
    const { container } = render(
      <Waveform activeBars={0} barColorClass="bg-accent" heights={real} />
    );

    expect(barHeights(container).slice(0, 5)).toEqual(new Array(5).fill('40%'));
  });

  it('fills bars up to the active count, whatever the heights are', () => {
    const { container } = render(
      <Waveform activeBars={2} barColorClass="bg-accent" heights={[1, 1, 1, 1]} />
    );

    const filled = slots(container)
      .filter((slot) => slot.style.height !== '')
      .map((slot) => slot.className.includes('bg-accent'));

    expect(filled).toEqual([true, true, false, false]);
  });

  it('still renders when given fewer heights than the design shape', () => {
    const { container } = render(
      <Waveform activeBars={1} barColorClass="bg-accent" heights={[0.6]} />
    );

    expect(barHeights(container)).toEqual(['60%']);
    expect(WAVE_HEIGHTS).toHaveLength(BAR_COUNT);
  });
});
