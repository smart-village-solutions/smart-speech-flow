import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppHeader } from '@/ui/patterns/AppHeader';

function setup() {
  const handlers = { onBack: vi.fn(), onHome: vi.fn(), onFeedback: vi.fn() };
  renderWithProviders(<AppHeader {...handlers} />);
  return handlers;
}

describe('AppHeader', () => {
  it('exposes back, home, feedback and theme controls', () => {
    setup();

    expect(screen.getByRole('button', { name: /^back$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /home/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^feedback$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /theme/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /brand/i })).not.toBeInTheDocument();
  });

  it('calls each handler', async () => {
    const handlers = setup();

    await userEvent.click(screen.getByRole('button', { name: /^back$/i }));
    await userEvent.click(screen.getByRole('button', { name: /home/i }));
    await userEvent.click(screen.getByRole('button', { name: /^feedback$/i }));

    expect(handlers.onBack).toHaveBeenCalledOnce();
    expect(handlers.onHome).toHaveBeenCalledOnce();
    expect(handlers.onFeedback).toHaveBeenCalledOnce();
  });

  it('renders the fixed logo in a white 180px header', () => {
    setup();

    const logo = screen.getByRole('img', { name: 'Smart Speech Flow' });
    expect(logo).toHaveAttribute('src', '/assets/Logo.png');
    expect(logo).toHaveClass('w-full');

    const header = screen.getByRole('banner');
    expect(header).toHaveClass('bg-white');
    expect(header.firstElementChild).toHaveClass('h-[180px]');
  });
});
