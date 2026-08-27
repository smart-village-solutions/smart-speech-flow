import { describe, expect, it } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { installFakeClipboard } from '@/test/fakeClipboard';
import { useCopyToClipboard } from '@/ui/hooks/useCopyToClipboard';

function Probe({ text }: Readonly<{ text: string }>) {
  const { state, copy } = useCopyToClipboard();
  return (
    <button type="button" onClick={() => void copy(text)}>
      {state}
    </button>
  );
}

describe('useCopyToClipboard', () => {
  it('starts idle', () => {
    installFakeClipboard();
    render(<Probe text="http://localhost:5173/join/A1B2C3D4" />);
    expect(screen.getByRole('button')).toHaveTextContent('idle');
  });

  it('writes exactly the text it was given', async () => {
    const clipboard = installFakeClipboard();
    render(<Probe text="http://localhost:5173/join/A1B2C3D4" />);

    await userEvent.click(screen.getByRole('button'));

    expect(clipboard.written).toEqual(['http://localhost:5173/join/A1B2C3D4']);
    expect(screen.getByRole('button')).toHaveTextContent('copied');
  });

  it('reports a refusal instead of claiming success', async () => {
    installFakeClipboard({ fail: true });
    render(<Probe text="http://localhost:5173/join/A1B2C3D4" />);

    await userEvent.click(screen.getByRole('button'));

    expect(screen.getByRole('button')).toHaveTextContent('failed');
  });

  it('returns to idle so the prompt comes back', async () => {
    installFakeClipboard();
    render(<Probe text="x" />);

    await userEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('button')).toHaveTextContent('copied');

    await act(async () => {
      await new Promise((resolve) => {
        setTimeout(resolve, 2100);
      });
    });

    expect(screen.getByRole('button')).toHaveTextContent('idle');
  });
});
