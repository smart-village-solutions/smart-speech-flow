import { useEffect, useState } from 'react';

/** The current time, re-read every second while `active`; frozen otherwise. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) {
      return;
    }
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);

  return now;
}
