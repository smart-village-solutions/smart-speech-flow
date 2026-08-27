import { useRef } from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FLIGHT_MS, useSendFlight } from '@/features/conversation/useSendFlight';

const RECTS: Record<string, Partial<DOMRect>> = {
  source: { left: 20, top: 600, width: 300, height: 100, bottom: 700 },
  landing: { left: 16, top: 300, width: 74, height: 58, bottom: 358 },
};

const ZERO = { top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 };

/** jsdom gives every element a zero rect, so the geometry has to be planted. */
function plantRects() {
  Element.prototype.getBoundingClientRect = function measured(this: Element) {
    const key = (this as HTMLElement).dataset?.testid ?? '';
    return { ...ZERO, ...RECTS[key] } as DOMRect;
  };
}

function Harness({ withSource = true, withLanding = true, pendingLanding = true }) {
  const targetRef = useRef<HTMLDivElement | null>(null);
  const { flight, sourceRef, launch } = useSendFlight(targetRef);

  return (
    <div>
      <div ref={targetRef}>
        {withLanding && (
          <div data-bubble {...(pendingLanding ? { 'data-pending': '' } : {})} data-testid="landing" />
        )}
      </div>
      {withSource && flight === null && <div ref={sourceRef} data-testid="source" />}
      <button type="button" onClick={() => launch('recording', '40px')}>
        launch
      </button>
      {flight !== null && (
        <div
          data-testid="flight"
          data-kind={flight.kind}
          data-bottom={flight.bottom}
          data-from={`${flight.from.width}x${flight.from.height}`}
          data-to={flight.to === null ? '' : `${flight.to.width}x${flight.to.height}`}
          data-transform={flight.to?.transform ?? ''}
        />
      )}
    </div>
  );
}

function launch() {
  act(() => {
    screen.getByRole('button', { name: 'launch' }).click();
  });
}

function nextFrame() {
  act(() => {
    vi.advanceTimersByTime(20);
  });
}

describe('useSendFlight', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    plantRects();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('holds the box at its launch size until the landing spot is measured', () => {
    render(<Harness />);

    launch();

    const box = screen.getByTestId('flight');
    expect(box.dataset.from).toBe('300x100');
    expect(box.dataset.to).toBe('');
    expect(box.dataset.kind).toBe('recording');
    expect(box.dataset.bottom).toBe('40px');
  });

  it('lands on the pending bubble exactly, matching its position and size', () => {
    render(<Harness />);

    launch();
    nextFrame();

    const box = screen.getByTestId('flight');
    // The landing bubble sits at (16, 300); the box launched from (20, 600).
    expect(box.dataset.transform).toBe('translate(-4px, -300px)');
    expect(box.dataset.to).toBe('74x58');
  });

  it('ends the flight once the animation is over', () => {
    render(<Harness />);

    launch();
    nextFrame();
    expect(screen.getByTestId('flight')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(FLIGHT_MS);
    });

    expect(screen.queryByTestId('flight')).not.toBeInTheDocument();
  });

  it('keeps the rect it cached while the box was on screen', () => {
    const { rerender } = render(<Harness />);

    // The recorder drops the box before handing the audio over.
    rerender(<Harness withSource={false} />);
    launch();

    expect(screen.getByTestId('flight').dataset.from).toBe('300x100');
  });

  it('falls back to the last bubble when the send confirms before it measures', () => {
    render(<Harness pendingLanding={false} />);

    launch();
    nextFrame();

    expect(screen.getByTestId('flight').dataset.to).toBe('74x58');
  });

  it('drops the flight when the stack holds no bubble to land on', () => {
    render(<Harness withLanding={false} />);

    launch();
    nextFrame();

    expect(screen.queryByTestId('flight')).not.toBeInTheDocument();
  });

  it('skips the flight when no box was ever on screen', () => {
    render(<Harness withSource={false} />);

    launch();

    expect(screen.queryByTestId('flight')).not.toBeInTheDocument();
  });
});
