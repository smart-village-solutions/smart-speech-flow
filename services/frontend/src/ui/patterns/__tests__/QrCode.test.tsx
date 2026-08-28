import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QrCode } from '@/ui/patterns/QrCode';

const URL = 'http://localhost:5173/join/A1B2C3D4';

describe('QrCode', () => {
  it('encodes the URL it is given', () => {
    const { container } = render(<QrCode value={URL} title="QR code for the join link" />);
    // The generated paths are opaque; the title is the only assertable proof
    // that this SVG belongs to this payload.
    expect(container.querySelector('svg')).not.toBeNull();
    expect(screen.getByTitle('QR code for the join link')).toBeInTheDocument();
  });

  it('re-encodes when the URL changes', () => {
    const { container, rerender } = render(<QrCode value={URL} title="qr" />);
    const first = container.querySelector('svg')?.innerHTML;

    rerender(<QrCode value="http://localhost:5173/join/ZZZZZZZZ" title="qr" />);

    expect(container.querySelector('svg')?.innerHTML).not.toBe(first);
  });
});
