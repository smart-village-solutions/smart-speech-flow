import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ScaleInput } from '@/ui/patterns/ScaleInput';

const scores = () => screen.getAllByRole('button').map((button) => button.textContent);

describe('ScaleInput', () => {
  it('offers zero to ten for the recommendation scale', () => {
    renderWithProviders(<ScaleInput min={0} max={10} value={null} onChange={vi.fn()} />);

    expect(scores()).toEqual(['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10']);
  });

  it('is not tied to zero to ten', () => {
    renderWithProviders(<ScaleInput min={1} max={7} value={null} onChange={vi.fn()} />);

    expect(scores()).toEqual(['1', '2', '3', '4', '5', '6', '7']);
  });

  it('treats zero as an answer, not as nothing chosen', async () => {
    const onChange = vi.fn();
    renderWithProviders(<ScaleInput min={0} max={10} value={0} onChange={onChange} />);

    expect(screen.getByRole('button', { name: 'Score 0' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Score 8' }));
    expect(onChange).toHaveBeenCalledWith(8);
  });

  it('labels the ends in one row, lowest first, when labels are given', () => {
    renderWithProviders(
      <ScaleInput min={0} max={10} value={null} onChange={vi.fn()} minLabel="Low" maxLabel="High" />
    );

    const low = screen.getByText('Low');
    expect(low.parentElement).toBe(screen.getByText('High').parentElement);
    expect(low.nextElementSibling).toHaveTextContent('High');
  });

  it('renders no label row without labels', () => {
    const { container } = renderWithProviders(
      <ScaleInput min={0} max={10} value={null} onChange={vi.fn()} />
    );

    expect(container.querySelectorAll('span')).toHaveLength(0);
  });
});
