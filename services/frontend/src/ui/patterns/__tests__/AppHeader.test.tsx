import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppHeader } from '@/ui/patterns/AppHeader';

function setup(brand: 'ssf' | 'kassel' = 'kassel') {
  const handlers = { onBack: vi.fn(), onHome: vi.fn(), onFeedback: vi.fn() };
  renderWithProviders(<AppHeader {...handlers} />, { brand });
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

    const logo = screen.getByRole('img', { name: 'KasselDIALOG' });
    expect(logo).toHaveAttribute('src', '/assets/Logo.png');
    expect(logo).toHaveClass('w-full');

    const header = screen.getByRole('banner');
    expect(header).toHaveClass('bg-white', 'shadow-[0_2px_6px_rgba(0,0,0,0.08)]');
    // The height is the token, so a compact shell (keyboard open) can shrink it.
    expect(header.firstElementChild).toHaveClass('h-header', 'content-start');
  });

  it('drops the logo block while the shell says the keyboard is open', () => {
    setup();

    const block = screen.getByRole('img', { name: 'KasselDIALOG' }).parentElement;
    expect(block).toHaveClass('h-header-logo', 'group-data-[keyboard=open]/shell:hidden');
  });

  it('uses the catalogue name instead of a Kassel image for another brand', () => {
    setup('ssf');

    expect(screen.getByText('KasselDIALOG')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'KasselDIALOG' })).not.toBeInTheDocument();
  });
});
