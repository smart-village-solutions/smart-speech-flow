import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { RecoveryModeChoice } from '../RecoveryModeChoice';

describe('RecoveryModeChoice', () => {
  it("offers the concept's two modes and reports the approvals each needs", async () => {
    const onChange = vi.fn();
    renderWithProviders(<RecoveryModeChoice k={2} onChange={onChange} />, { locale: 'de' });
    const standard = screen.getByRole('radio', {
      name: /Standard-Wiederherstellung: Eine Freigabe genügt/,
    });
    const enhanced = screen.getByRole('radio', {
      name: /Erweiterte Wiederherstellung: 2 Freigaben nötig/,
    });
    expect(screen.getAllByRole('radio')).toHaveLength(2);
    expect(enhanced).toBeChecked();
    await userEvent.click(standard);
    expect(onChange).toHaveBeenCalledWith(1);
  });

  it('keeps an older key that needs more approvals as a third choice', () => {
    renderWithProviders(<RecoveryModeChoice k={3} onChange={vi.fn()} />, { locale: 'de' });
    expect(screen.getAllByRole('radio')).toHaveLength(3);
    expect(
      screen.getByRole('radio', { name: /Erweiterte Wiederherstellung: 3 Freigaben nötig/ })
    ).toBeChecked();
  });
});
