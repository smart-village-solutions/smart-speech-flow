import { useState } from 'react';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { CODE_LENGTH, normalizeCode } from '@/lib/accessCode';
import { CodeInput } from '@/ui/patterns/CodeInput';

function Harness() {
  const [value, setValue] = useState('');
  return (
    <>
      <CodeInput value={value} onChange={setValue} />
      <output>{normalizeCode(value)}</output>
    </>
  );
}

describe('CodeInput', () => {
  it('renders one box per code character', () => {
    renderWithProviders(<Harness />);
    expect(screen.getAllByRole('textbox')).toHaveLength(CODE_LENGTH);
  });

  it('advances to the next box as characters are typed', async () => {
    renderWithProviders(<Harness />);
    const boxes = screen.getAllByRole('textbox');

    await userEvent.click(boxes[0]);
    await userEvent.keyboard('AB');

    expect(screen.getByRole('status')).toHaveTextContent('AB');
    expect(boxes[2]).toHaveFocus();
  });

  it('uppercases input, matching the gateway session id alphabet', async () => {
    renderWithProviders(<Harness />);

    await userEvent.click(screen.getAllByRole('textbox')[0]);
    await userEvent.keyboard('a1');

    expect(screen.getByRole('status')).toHaveTextContent('A1');
  });

  it('distributes a pasted code across the boxes', async () => {
    renderWithProviders(<Harness />);

    await userEvent.click(screen.getAllByRole('textbox')[0]);
    await userEvent.paste('a1b2c3d4');

    expect(screen.getByRole('status')).toHaveTextContent('A1B2C3D4');
  });

  it('steps back on backspace in an empty box', async () => {
    renderWithProviders(<Harness />);
    const boxes = screen.getAllByRole('textbox');

    await userEvent.click(boxes[0]);
    await userEvent.keyboard('A');
    await userEvent.keyboard('{Backspace}{Backspace}');

    expect(screen.getByRole('status').textContent).toBe('');
    expect(boxes[0]).toHaveFocus();
  });

  it('does not shift later characters when an interior box is cleared', async () => {
    renderWithProviders(<Harness />);
    const boxes = screen.getAllByRole('textbox');

    await userEvent.click(boxes[0]);
    await userEvent.paste('A1B2C3D4');

    await userEvent.click(boxes[1]);
    await userEvent.keyboard('{Backspace}');

    expect(boxes[0]).toHaveValue('A');
    expect(boxes[1]).toHaveValue('');
    expect(boxes[2]).toHaveValue('B');
  });
});
