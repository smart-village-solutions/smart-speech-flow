import { useEffect, useId, useRef, type PointerEvent } from 'react';
import { useTranslation } from 'react-i18next';

interface SignaturePadProps {
  /** The label, with "optional" already added when it is. */
  label: string;
  /** The drawn PNG as base64, or null once cleared. */
  onChange: (png: string | null) => void;
}

/** Device pixels of the stroke at a ratio of one (SCREEN_SPECS "Guest recording question"). */
const STROKE = 2;

function context(canvas: HTMLCanvasElement | null): CanvasRenderingContext2D | null {
  return canvas?.getContext('2d') ?? null;
}

/**
 * Fits the bitmap to the pad at the device's pixel ratio and lays down the
 * paper. The paper is painted, not styled, so the archived PNG is dark ink on
 * white whatever the screen's theme.
 */
function prepare(pad: HTMLCanvasElement): void {
  const pen = context(pad);
  if (pen === null) return;
  const ratio = globalThis.devicePixelRatio || 1;
  pad.width = Math.round(pad.clientWidth * ratio);
  pad.height = Math.round(pad.clientHeight * ratio);
  const look = getComputedStyle(pad);
  pen.fillStyle = look.backgroundColor;
  pen.fillRect(0, 0, pad.width, pad.height);
  pen.lineWidth = STROKE * ratio;
  pen.lineCap = 'round';
  pen.lineJoin = 'round';
  pen.strokeStyle = look.color;
}

/**
 * A signature drawn with a finger, stylus or mouse (spec §6). Only a stroke
 * counts: a tap leaves the pad unsigned. One pointer draws at a time, and a
 * pad that changes size (a rotated tablet) starts over rather than stretching.
 * It has no keyboard path of its own: the dialog's "cannot sign" is that path.
 */
export function SignaturePad({ label, onChange }: Readonly<SignaturePadProps>) {
  const { t } = useTranslation();
  const id = useId();
  const canvas = useRef<HTMLCanvasElement>(null);
  const pointer = useRef<number | null>(null);
  const moved = useRef(false);
  // The resize observer outlives renders; it calls whichever handler is current.
  const change = useRef(onChange);
  useEffect(() => {
    change.current = onChange;
  });

  useEffect(() => {
    const pad = canvas.current;
    if (pad === null) return;
    prepare(pad);
    if (typeof ResizeObserver === 'undefined') return;
    let size = `${pad.clientWidth}x${pad.clientHeight}`;
    const observer = new ResizeObserver(() => {
      const next = `${pad.clientWidth}x${pad.clientHeight}`;
      if (next === size) return;
      size = next;
      prepare(pad);
      change.current(null);
    });
    observer.observe(pad);
    return () => observer.disconnect();
  }, []);

  const at = (event: PointerEvent<HTMLCanvasElement>): [number, number] => {
    const pad = event.currentTarget;
    const box = pad.getBoundingClientRect();
    return [
      ((event.clientX - box.left) * pad.width) / box.width,
      ((event.clientY - box.top) * pad.height) / box.height,
    ];
  };

  const start = (event: PointerEvent<HTMLCanvasElement>) => {
    const pen = context(event.currentTarget);
    if (pen === null || pointer.current !== null) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    pointer.current = event.pointerId;
    moved.current = false;
    pen.beginPath();
    pen.moveTo(...at(event));
  };

  const move = (event: PointerEvent<HTMLCanvasElement>) => {
    const pen = context(event.currentTarget);
    if (pointer.current !== event.pointerId || pen === null) return;
    pen.lineTo(...at(event));
    pen.stroke();
    moved.current = true;
  };

  const end = (event: PointerEvent<HTMLCanvasElement>) => {
    if (pointer.current !== event.pointerId) return;
    pointer.current = null;
    if (!moved.current) return;
    // An unmeasured pad exports "data:," — nothing to send.
    onChange(event.currentTarget.toDataURL('image/png').split(',')[1] || null);
  };

  const clear = () => {
    const pad = canvas.current;
    if (pad !== null) prepare(pad);
    onChange(null);
  };

  return (
    <div className="mt-4 flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-3">
        <span id={id} className="text-label font-medium text-fg-body">
          {label}
        </span>
        <button type="button" onClick={clear} className="text-label font-medium text-fg-link">
          {t('recording.consent.clear')}
        </button>
      </div>
      <canvas
        ref={canvas}
        aria-labelledby={id}
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
        className="h-signature-pad w-full touch-none rounded-xl border border-border-card bg-signature-paper text-signature-ink"
      />
    </div>
  );
}
