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
  it('exposes back, home, feedback, theme and brand controls', () => {
    setup();

    expect(screen.getByRole('button', { name: /^back$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /home/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^feedback$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /theme/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /brand/i })).toBeInTheDocument();
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

  it('switches the brand logo when the brand control is used', async () => {
    setup();

    expect(screen.getByRole('img', { name: 'Smart Speech Flow' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /brand/i }));

    expect(screen.getByRole('img', { name: 'Kassel Dialog' })).toBeInTheDocument();
  });
});
