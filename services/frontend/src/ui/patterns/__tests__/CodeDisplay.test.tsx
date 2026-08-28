import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CodeDisplay } from '@/ui/patterns/CodeDisplay';

describe('CodeDisplay', () => {
  it('shows one box per character', () => {
    const { container } = render(<CodeDisplay code="A1B2C3D4" label="Session code A1B2C3D4" />);
    expect(container.querySelectorAll('[data-code-box]')).toHaveLength(8);
  });

  it('names the whole code for assistive technology once, not character by character', () => {
    render(<CodeDisplay code="A1B2C3D4" label="Session code A1B2C3D4" />);
    expect(screen.getByText('Session code A1B2C3D4')).toBeInTheDocument();
  });

  it('renders the code left to right whatever the page direction is', () => {
    const { container } = render(<CodeDisplay code="A1B2C3D4" label="code" />);
    expect(container.querySelector('[dir="ltr"]')).not.toBeNull();
  });

  it('upper-cases what the gateway sent, defensively', () => {
    const { container } = render(<CodeDisplay code="a1b2c3d4" label="code" />);
    const boxes = [...container.querySelectorAll('[data-code-box]')].map((box) => box.textContent);
    expect(boxes.join('')).toBe('A1B2C3D4');
  });
});
