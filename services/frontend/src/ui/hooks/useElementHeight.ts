import { useEffect, useState, type RefObject } from 'react';

/** The element's rendered height in whole px; 0 before layout and where ResizeObserver is missing. */
export function useElementHeight(ref: RefObject<HTMLElement | null>): number {
  const [height, setHeight] = useState(0);

  useEffect(() => {
    const element = ref.current;
    if (element === null || typeof ResizeObserver === 'undefined') return;

    const observer = new ResizeObserver(([entry]) => {
      setHeight(Math.ceil(entry.contentRect.height));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return height;
}
