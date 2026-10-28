import { act, fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { SignaturePad } from '../SignaturePad';

function mockCanvas() {
  const pen = {
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fillRect: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    pen as unknown as CanvasRenderingContext2D
  );
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,QQ');
  HTMLCanvasElement.prototype.setPointerCapture = vi.fn();
  return pen;
}

function render() {
  const onChange = vi.fn();
  renderWithProviders(<SignaturePad label="Signature" onChange={onChange} />);
  return { onChange, pad: screen.getByLabelText('Signature') };
}

const down = (pad: Element, pointerId: number) =>
  fireEvent.pointerDown(pad, { pointerId, clientX: 1, clientY: 1 });
const move = (pad: Element, pointerId: number) =>
  fireEvent.pointerMove(pad, { pointerId, clientX: 9, clientY: 9 });
const up = (pad: Element, pointerId: number) => fireEvent.pointerUp(pad, { pointerId });

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('SignaturePad', () => {
  it('lays down the paper before anything is drawn', () => {
    const pen = mockCanvas();
    render();
    expect(pen.fillRect).toHaveBeenCalledOnce();
  });

  it('sends a stroke, and nothing for a tap', () => {
    mockCanvas();
    const { onChange, pad } = render();

    down(pad, 1);
    up(pad, 1);
    expect(onChange).not.toHaveBeenCalled();

    down(pad, 1);
    move(pad, 1);
    up(pad, 1);
    expect(onChange).toHaveBeenCalledWith('QQ');
  });

  it('follows one pointer only, so a second finger draws nothing', () => {
    const pen = mockCanvas();
    const { onChange, pad } = render();

    down(pad, 1);
    down(pad, 2);
    move(pad, 2);
    up(pad, 2);

    expect(pen.lineTo).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('starts over when the pad changes size', () => {
    const pen = mockCanvas();
    let resized = () => {};
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: () => void) {
          resized = callback;
        }
        observe() {}
        disconnect() {}
      }
    );
    const { onChange, pad } = render();
    Object.defineProperty(pad, 'clientWidth', { configurable: true, value: 640 });

    act(() => resized());

    expect(onChange).toHaveBeenCalledWith(null);
    expect(pen.fillRect).toHaveBeenCalledTimes(2);
  });

  it('sends nothing from a pad that was never measured', () => {
    mockCanvas();
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:,');
    const { onChange, pad } = render();

    down(pad, 1);
    move(pad, 1);
    up(pad, 1);

    expect(onChange).toHaveBeenCalledWith(null);
  });
});
