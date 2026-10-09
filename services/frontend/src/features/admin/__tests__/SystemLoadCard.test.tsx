import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { SystemLoadCard } from '@/features/admin/SystemLoadCard';
import type { SystemLoadLevel } from '@/domain/health/health.types';
import type { LoadCopy } from '@/features/content/staffCopy';
import { bundledStaffCopy } from '@/test/staffCopy';

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
      renderWithProviders(<SystemLoadCard copy={bundledStaffCopy().load} />, {
        locale: 'de',
        services: returning(level),
      });
      expect(await screen.findByText(LABELS[level])).toBeInTheDocument();
    }
  );

  it('shows unknown rather than available when the request fails', async () => {
    renderWithProviders(<SystemLoadCard copy={bundledStaffCopy().load} />, {
      locale: 'de',
      services: { health: { getSystemLoad: () => Promise.reject(new Error('gateway down')) } },
    });

    expect(await screen.findByText(LABELS.unknown)).toBeInTheDocument();
    expect(screen.queryByText(LABELS.ok)).not.toBeInTheDocument();
  });

  it('is not a clickable control, unlike the prototype', async () => {
    renderWithProviders(<SystemLoadCard copy={bundledStaffCopy().load} />, {
      locale: 'de',
      services: returning('ok'),
    });

    await screen.findByText(LABELS.ok);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('names the card', async () => {
    renderWithProviders(<SystemLoadCard copy={bundledStaffCopy().load} />, {
      locale: 'de',
      services: returning('ok'),
    });
    expect(await screen.findByText('Systemauslastung')).toBeInTheDocument();
  });

  it('shows the label and title it is given for the level', async () => {
    const copy: LoadCopy = {
      headline: 'Studio-Auslastung',
      levels: {
        ok: 'Studio grün',
        delayed: 'Studio gelb',
        unavailable: 'Studio rot',
        unknown: '?',
      },
    };
    renderWithProviders(<SystemLoadCard copy={copy} />, {
      locale: 'de',
      services: returning('delayed'),
    });

    expect(await screen.findByText('Studio gelb')).toBeInTheDocument();
    expect(screen.getByText('Studio-Auslastung')).toBeInTheDocument();
  });
});
