import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';

describe('test infrastructure', () => {
  it('renders a component through the shared render helper', () => {
    renderWithProviders(<p>ready</p>);
    expect(screen.getByText('ready')).toBeInTheDocument();
  });
});
