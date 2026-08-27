import { QRCodeSVG } from 'qrcode.react';

/** SCREEN_SPECS "Admin invite overlay": a 100px module area on a white plate. */
const MODULE_PIXELS = 100;

interface QrCodeProps {
  value: string;
  /** Names the image; the payload is also on screen as text beside it. */
  title: string;
}

/**
 * The only import site of `qrcode.react`, so the encoder can be replaced from
 * one file. The plate is white in both themes because a dark-on-dark code does
 * not scan; the ink is a custom property read straight by the SVG `fill`, since
 * the library takes colour values rather than class names.
 */
export function QrCode({ value, title }: Readonly<QrCodeProps>) {
  return (
    <div className="overflow-hidden rounded-row bg-qr-plate p-2">
      <QRCodeSVG
        value={value}
        title={title}
        size={MODULE_PIXELS}
        bgColor="transparent"
        fgColor="var(--qr-ink)"
      />
    </div>
  );
}
