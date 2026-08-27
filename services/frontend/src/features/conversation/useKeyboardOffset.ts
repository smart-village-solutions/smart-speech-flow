import { useEffect, useState } from 'react';

/**
 * How far the software keyboard has pushed up the visual viewport, so the
 * composer and mic row can sit above it. Returns 0 where visualViewport is
 * unavailable, which includes jsdom.
 */
export function useKeyboardOffset(): number {
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const viewport = window.visualViewport;

    if (!viewport) {
      return;
    }

    const update = () => {
      setOffset(Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop));
    };

    viewport.addEventListener('resize', update);
    viewport.addEventListener('scroll', update);

    return () => {
      viewport.removeEventListener('resize', update);
      viewport.removeEventListener('scroll', update);
    };
  }, []);

  return offset;
}
