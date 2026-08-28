import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TextField } from '@/ui/primitives/TextField';

describe('TextField', () => {
  it('associates its label with the input', () => {
    render(<TextField label="Email address" />);
    expect(screen.getByLabelText('Email address')).toBeInTheDocument();
  });

  it('keeps a hidden label reachable by assistive technology', () => {
    render(<TextField label="New password" labelHidden type="password" />);
    expect(screen.getByLabelText('New password')).toHaveAttribute('type', 'password');
    expect(screen.getByText('New password')).toHaveClass('sr-only');
  });

  it('passes through input attributes', () => {
    render(<TextField label="Email" type="email" placeholder="admin@example.com" />);
    expect(screen.getByLabelText('Email')).toHaveAttribute('placeholder', 'admin@example.com');
  });

  it('generates a distinct id per instance', () => {
    render(
      <>
        <TextField label="One" />
        <TextField label="Two" />
      </>
    );
    expect(screen.getByLabelText('One').id).not.toBe(screen.getByLabelText('Two').id);
  });

  it('defaults to a text input', () => {
    render(<TextField label="Anything" />);
    expect(screen.getByLabelText('Anything')).toHaveAttribute('type', 'text');
  });

  it('announces a field error and marks the input invalid', () => {
    render(<TextField label="Email" error="Bad address" />);

    expect(screen.getByRole('alert')).toHaveTextContent('Bad address');
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true');
  });

  it('marks nothing invalid without an error', () => {
    render(<TextField label="Email" />);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Email')).not.toHaveAttribute('aria-invalid');
  });
});
