import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RecordingBubble } from '@/ui/patterns/RecordingBubble';

/** Only the slots carrying a bar; the row always reserves BAR_COUNT slots. */
function bars(container: HTMLElement) {
  return [...container.querySelectorAll<HTMLElement>('[aria-hidden="true"] > div')].filter(
    (slot) => slot.style.height !== ''
  );
}

describe('RecordingBubble', () => {
  it('draws one bar per measured window, at the loudness measured', () => {
    const { container } = render(
      <RecordingBubble levels={[1, 0.5, 0.2]} elapsedSeconds={1.2} totalSeconds={20} />
    );

    expect(bars(container).map((bar) => bar.style.height)).toEqual(['100%', '50%', '20%']);
  });

  it('colours every drawn bar, since each one is audio already heard', () => {
    const { container } = render(
      <RecordingBubble levels={[1, 0.5]} elapsedSeconds={0.8} totalSeconds={20} />
    );

    expect(bars(container).every((bar) => bar.className.includes('bg-recording'))).toBe(true);
  });

  it('shows an empty row before anything has been said', () => {
    const { container } = render(
      <RecordingBubble levels={[]} elapsedSeconds={0} totalSeconds={20} />
    );

    expect(bars(container)).toHaveLength(0);
  });

  it('counts elapsed time up and remaining time down', () => {
    render(<RecordingBubble levels={[]} elapsedSeconds={5} totalSeconds={20} />);

    expect(screen.getByText('00:05')).toBeInTheDocument();
    expect(screen.getByText('-00:15')).toBeInTheDocument();
  });
});
