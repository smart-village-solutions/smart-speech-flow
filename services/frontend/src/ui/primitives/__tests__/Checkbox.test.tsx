import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Checkbox } from '@/ui/primitives/Checkbox';

describe('Checkbox', () => {
  it('exposes a real checkbox labelled by its children', () => {
    render(
      <Checkbox checked={false} onCheckedChange={vi.fn()}>
        I agree
      </Checkbox>
    );

    expect(screen.getByRole('checkbox', { name: 'I agree' })).not.toBeChecked();
  });

  it('reports changes', async () => {
    const onCheckedChange = vi.fn();
    render(
      <Checkbox checked={false} onCheckedChange={onCheckedChange}>
        I agree
      </Checkbox>
    );

    await userEvent.click(screen.getByRole('checkbox'));

    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it('reflects the checked prop', () => {
    render(
      <Checkbox checked onCheckedChange={vi.fn()}>
        I agree
      </Checkbox>
    );

    expect(screen.getByRole('checkbox')).toBeChecked();
  });
});
