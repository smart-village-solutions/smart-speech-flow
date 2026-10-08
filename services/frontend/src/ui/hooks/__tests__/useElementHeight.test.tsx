import { act, render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useElementHeight } from '@/ui/hooks/useElementHeight';

function Measured() {
  const ref = useRef<HTMLDivElement | null>(null);
  const height = useElementHeight(ref);
  return (
    <div ref={ref}>
      <output>{height}</output>
    </div>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useElementHeight', () => {
  it('reads 0 where ResizeObserver is unavailable', () => {
    vi.stubGlobal('ResizeObserver', undefined);
    render(<Measured />);

    expect(screen.getByRole('status')).toHaveTextContent('0');
  });

  it('follows the observed height, rounded up, and stops observing on unmount', () => {
    let report!: (height: number) => void;
    const disconnect = vi.fn();
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: ResizeObserverCallback) {
          report = (height) =>
            callback(
              [{ contentRect: { height } } as ResizeObserverEntry],
              this as unknown as ResizeObserver
            );
        }
        observe() {}
        disconnect = disconnect;
      }
    );
    const { unmount } = render(<Measured />);

    act(() => report(70.5));
    expect(screen.getByRole('status')).toHaveTextContent('71');

    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });
});
