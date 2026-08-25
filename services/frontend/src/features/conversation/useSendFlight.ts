import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

/** Keep in step with the `.send-flight` transition duration in `src/index.css`. */
export const FLIGHT_MS = 650;

/** Marks the bubble a flight aims for. Set by `MessageBubble` while pending. */
export const LANDING_ATTRIBUTE = 'data-pending';

/** Every bubble, in case the send confirms before the flight is measured. */
export const BUBBLE_ATTRIBUTE = 'data-bubble';

export type FlightKind = 'recording' | 'typing';

interface Box {
  width: number;
  height: number;
}

export interface SendFlight {
  kind: FlightKind;
  /** The composer offset at launch, held so a closing keyboard cannot drag the
      box back down mid-climb. */
  bottom: string;
  /** Launch geometry, frozen so the box keeps its size once it shows dots. */
  from: Box;
  /** Null until the pending bubble has been measured on the next frame. */
  to: (Box & { transform: string }) | null;
}

export interface UseSendFlightResult {
  /** Non-null while a composer box is travelling to the stack. */
  flight: SendFlight | null;
  /** Attach to whichever composer box is currently on screen. */
  sourceRef: RefObject<HTMLDivElement | null>;
  launch: (kind: FlightKind, bottom: string) => void;
}

/**
 * Flies the composer box up to the pending bubble, so a send reads as the
 * recording becoming the processing indicator.
 *
 * The landing spot is measured rather than predicted: the flight starts on the
 * frame after the pending bubble renders, so it can settle on the bubble's real
 * position and size instead of guessing where the stack will grow to.
 *
 * The source rect is cached on every render rather than read at launch time —
 * `useAudioRecorder` resets its phase before handing the audio over, so by the
 * time a recording send starts the box is already leaving the tree.
 */
export function useSendFlight(targetRef: RefObject<HTMLElement | null>): UseSendFlightResult {
  const sourceRef = useRef<HTMLDivElement | null>(null);
  const rectRef = useRef<DOMRect | null>(null);
  const [flight, setFlight] = useState<SendFlight | null>(null);

  useLayoutEffect(() => {
    if (flight === null && sourceRef.current !== null) {
      rectRef.current = sourceRef.current.getBoundingClientRect();
    }
  });

  const launch = useCallback((kind: FlightKind, bottom: string) => {
    const from = rectRef.current;
    if (from === null) {
      return;
    }
    setFlight({ kind, bottom, from: { width: from.width, height: from.height }, to: null });
  }, []);

  // One painted frame at the launch geometry is what gives the transition a
  // start value; the pending bubble has settled by the time this runs.
  useEffect(() => {
    if (flight === null || flight.to !== null) {
      return;
    }

    const frame = requestAnimationFrame(() => {
      const from = rectRef.current;
      const stack = targetRef.current;
      const landing =
        stack?.querySelector(`[${LANDING_ATTRIBUTE}]`) ??
        stack?.querySelector(`[${BUBBLE_ATTRIBUTE}]:last-of-type`) ??
        null;
      if (from === null || landing === null) {
        setFlight(null);
        return;
      }

      const to = landing.getBoundingClientRect();
      setFlight((current) =>
        current === null
          ? null
          : {
              ...current,
              to: {
                width: to.width,
                height: to.height,
                transform: `translate(${to.left - from.left}px, ${to.top - from.top}px)`,
              },
            }
      );
    });

    return () => cancelAnimationFrame(frame);
  }, [flight, targetRef]);

  useEffect(() => {
    if (flight?.to == null) {
      return;
    }
    const landed = setTimeout(() => setFlight(null), FLIGHT_MS);
    return () => clearTimeout(landed);
  }, [flight]);

  return { flight, sourceRef, launch };
}
