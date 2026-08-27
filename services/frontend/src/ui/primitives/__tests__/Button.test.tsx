import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Button } from '@/ui/primitives/Button';

describe('Button', () => {
  it('renders its children and fires onClick', async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Continue</Button>);

    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(onClick).toHaveBeenCalledOnce();
  });

  it('defaults to the pill variant', () => {
    render(<Button>Continue</Button>);
    expect(screen.getByRole('button')).toHaveClass('rounded-pill');
  });

  it('applies the sheet variant when asked', () => {
    render(<Button variant="sheet">Send feedback</Button>);
    expect(screen.getByRole('button')).toHaveClass('rounded-2xl');
  });

  it('does not fire when disabled', async () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Continue
      </Button>
    );

    await userEvent.click(screen.getByRole('button'));

    expect(onClick).not.toHaveBeenCalled();
  });
});
