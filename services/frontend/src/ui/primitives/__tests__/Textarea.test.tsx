import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Textarea } from '@/ui/primitives/Textarea';

describe('Textarea', () => {
  it.each(['plain', 'field'] as const)(
    'keeps the %s variant a labelled editable textarea',
    async (variant) => {
      const change = vi.fn();
      render(<Textarea variant={variant} aria-label="Message" onChange={change} />);
      await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'Hello');
      expect(screen.getByRole('textbox')).toHaveValue('Hello');
      expect(change).toHaveBeenCalled();
    }
  );

  it('preserves native invalid descriptions and disabled behavior', async () => {
    const change = vi.fn();
    render(
      <>
        <Textarea
          aria-label="Message"
          aria-invalid
          aria-describedby="error"
          disabled
          onChange={change}
        />
        <p id="error">Required</p>
      </>
    );
    expect(screen.getByRole('textbox')).toHaveAccessibleDescription('Required');
    expect(screen.getByRole('textbox')).toBeInvalid();
    await userEvent.type(screen.getByRole('textbox'), 'Ignored');
    expect(change).not.toHaveBeenCalled();
  });
});
