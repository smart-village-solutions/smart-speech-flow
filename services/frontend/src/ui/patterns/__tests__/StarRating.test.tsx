import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { StarRating } from '@/ui/patterns/StarRating';

const stars = () =>
  screen.getAllByRole('button').map((button) => button.getAttribute('aria-label'));

describe('StarRating', () => {
  it('offers one star per value from min to max', () => {
    renderWithProviders(<StarRating min={1} max={5} value={null} onChange={vi.fn()} />);

    expect(stars()).toEqual(['1 stars', '2 stars', '3 stars', '4 stars', '5 stars']);
  });

  it('is not tied to five stars', () => {
    renderWithProviders(<StarRating min={1} max={7} value={null} onChange={vi.fn()} />);

    expect(stars()).toHaveLength(7);
    expect(stars().at(-1)).toBe('7 stars');
  });

  it('reports the chosen value and marks the current one pressed', async () => {
    const onChange = vi.fn();
    renderWithProviders(<StarRating min={1} max={5} value={3} onChange={onChange} />);

    expect(screen.getByRole('button', { name: '3 stars' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: '5 stars' }));
    expect(onChange).toHaveBeenCalledWith(5);
  });
});
