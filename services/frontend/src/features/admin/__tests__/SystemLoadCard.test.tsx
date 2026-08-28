import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { SystemLoadCard } from '@/features/admin/SystemLoadCard';
import type { SystemLoadLevel } from '@/domain/health/health.types';

const returning = (level: SystemLoadLevel) => ({
  health: { getSystemLoad: () => Promise.resolve({ level }) },
});

const LABELS: Record<SystemLoadLevel, string> = {
  ok: 'Ausreichend Kapazitäten verfügbar',
  delayed: 'Es kann zu kurzen Wartezeiten kommen',
  unavailable: 'Derzeit sind keine weiteren Gespräche möglich',
  unknown: 'Systemauslastung nicht abrufbar',
};

describe('SystemLoadCard', () => {
  it.each(['ok', 'delayed', 'unavailable', 'unknown'] as const)(
    'renders the %s state',
    async (level) => {
      renderWithProviders(<SystemLoadCard />, { locale: 'de', services: returning(level) });
      expect(await screen.findByText(LABELS[level])).toBeInTheDocument();
    }
  );

  it('shows unknown rather than available when the request fails', async () => {
    renderWithProviders(<SystemLoadCard />, {
      locale: 'de',
      services: { health: { getSystemLoad: () => Promise.reject(new Error('gateway down')) } },
    });

    expect(await screen.findByText(LABELS.unknown)).toBeInTheDocument();
    expect(screen.queryByText(LABELS.ok)).not.toBeInTheDocument();
  });

  it('is not a clickable control, unlike the prototype', async () => {
    renderWithProviders(<SystemLoadCard />, { locale: 'de', services: returning('ok') });

    await screen.findByText(LABELS.ok);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('names the card', async () => {
    renderWithProviders(<SystemLoadCard />, { locale: 'de', services: returning('ok') });
    expect(await screen.findByText('Systemauslastung')).toBeInTheDocument();
  });
});
