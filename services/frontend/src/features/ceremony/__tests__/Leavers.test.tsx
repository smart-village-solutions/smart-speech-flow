import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity, hasFreshStepUp, hasPermission } from '@/app/auth/keycloak';
import { AppError } from '@/core/http/AppError';
import type { LeaverCandidate } from '@/domain/recovery/recovery.types';
import { installFakeClipboard } from '@/test/fakeClipboard';
import { activeKey, render } from './ceremonyHarness';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasPermission: vi.fn(),
  hasFreshStepUp: vi.fn(),
  requestStepUp: vi.fn(),
}));

const alice: LeaverCandidate = {
  sub: '7f1e2d3c-alice',
  keyVersion: 2,
  fingerprintDisplay: 'ab12 cd34',
  enrolledAt: '2026-01-15T09:00:00+00:00',
  conversations: 12,
  lastConversationAt: '2026-09-30T14:00:00+00:00',
  custodian: false,
  displayName: null,
};
const carla: LeaverCandidate = {
  ...alice,
  sub: 'carla',
  custodian: true,
  displayName: 'Carla',
  lastConversationAt: null,
};
const withKey = { recoveryKey: activeKey(), ceremony: null, lastFailed: null, chain: null };

function refused(code: string) {
  return new AppError('validation', { status: 409, serverCode: code });
}

describe('leavers', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    vi.mocked(hasFreshStepUp).mockReturnValue(true);
  });

  it('lists what recognises a leaver without a name', async () => {
    render(withKey, { repository: { leavers: vi.fn().mockResolvedValue([alice, carla]) } });
    expect(await screen.findByText('7f1e2d3c-alice', { selector: 'span' })).toBeInTheDocument();
    expect(
      screen.getByText(/Eingerichtet am 15\.01\.2026 · Gespräche: 12 · letztes am 30\.09\.2026/)
    ).toBeInTheDocument();
    expect(screen.getByText('Carla')).toBeInTheDocument();
    expect(screen.getByText('Verwahrende')).toBeInTheDocument();
    expect(screen.getByText(/noch kein Gespräch/)).toBeInTheDocument();
  });

  it('copies the sub for a lookup in Studio', async () => {
    const clipboard = installFakeClipboard();
    render(withKey, { repository: { leavers: vi.fn().mockResolvedValue([alice]) } });
    await userEvent.click(await screen.findByRole('button', { name: 'Kennung kopieren' }));
    expect(clipboard.written).toEqual(['7f1e2d3c-alice']);
    expect(await screen.findByRole('button', { name: 'Kopiert' })).toBeInTheDocument();
  });

  it('marks a leaver by the version it showed, after a confirmation, and refreshes', async () => {
    const { recoveryCeremony } = render(withKey, {
      repository: { leavers: vi.fn().mockResolvedValueOnce([alice]).mockResolvedValue([]) },
    });
    await userEvent.click(
      await screen.findByRole('button', { name: 'Als ausgeschieden markieren' })
    );
    expect(screen.getByText(/über den Ausnahmezugang erreichbar/)).toBeInTheDocument();
    expect(screen.queryByText(/Ihr Anteil bleibt/)).not.toBeInTheDocument();
    expect(recoveryCeremony.markLeaver).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Endgültig markieren' }));
    await waitFor(() =>
      expect(recoveryCeremony.markLeaver).toHaveBeenCalledWith('7f1e2d3c-alice', 2)
    );
    expect(await screen.findByText(/Niemand:/)).toBeInTheDocument();
    expect(recoveryCeremony.state).toHaveBeenCalledTimes(2);
  });

  it('warns that a custodian’s share stays, and a cancel sends nothing', async () => {
    const { recoveryCeremony } = render(withKey, {
      repository: { leavers: vi.fn().mockResolvedValue([carla]) },
    });
    await userEvent.click(
      await screen.findByRole('button', { name: 'Als ausgeschieden markieren' })
    );
    expect(
      screen.getByText(/Ihr Anteil bleibt, bis die Verwahrenden geändert sind/)
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(screen.getByRole('button', { name: 'Als ausgeschieden markieren' })).toBeInTheDocument();
    expect(recoveryCeremony.markLeaver).not.toHaveBeenCalled();
  });

  it('asks for a fresh MFA login only once a marking is asked for, never on paper', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    const { recoveryCeremony } = render(withKey, {
      repository: { leavers: vi.fn().mockResolvedValue([alice]) },
    });
    await userEvent.click(
      await screen.findByRole('button', { name: 'Als ausgeschieden markieren' })
    );
    const prompt = screen.getByText('Identität bestätigen').closest('section');
    expect(prompt).toHaveClass('print:hidden');
    expect(screen.queryByRole('button', { name: 'Endgültig markieren' })).not.toBeInTheDocument();
    expect(recoveryCeremony.markLeaver).not.toHaveBeenCalled();
  });

  it('shows no login card for candidates nobody has asked to mark', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    render(withKey, { repository: { leavers: vi.fn().mockResolvedValue([alice]) } });
    expect(await screen.findByText('7f1e2d3c-alice', { selector: 'span' })).toBeInTheDocument();
    expect(screen.queryByText('Identität bestätigen')).not.toBeInTheDocument();
  });

  it('asks for no login while nobody has left', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    render(withKey);
    expect(await screen.findByText(/Niemand:/)).toBeInTheDocument();
    expect(screen.queryByText('Identität bestätigen')).not.toBeInTheDocument();
  });

  it.each([
    ['STILL_IN_DIRECTORY', /wieder eine Aufnahmeberechtigung/],
    ['ALREADY_LEFT', /bereits als ausgeschieden markiert/],
    ['KEY_NOT_ENROLLED', /keinen aktiven Archivschlüssel mehr/],
    ['KEY_CHANGED', /Laden Sie die Liste neu/],
    ['CEREMONY_IN_PROGRESS', /laufenden Schlüsselzeremonie/],
    ['SOMETHING_ELSE', /Das hat nicht geklappt/],
  ])('names a refused marking: %s', async (code, message) => {
    render(withKey, {
      repository: {
        leavers: vi.fn().mockResolvedValue([alice]),
        markLeaver: vi.fn().mockRejectedValue(refused(code)),
      },
    });
    await userEvent.click(
      await screen.findByRole('button', { name: 'Als ausgeschieden markieren' })
    );
    await userEvent.click(screen.getByRole('button', { name: 'Endgültig markieren' }));
    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it('clears a refusal once a candidate is asked about again', async () => {
    render(withKey, {
      repository: {
        leavers: vi.fn().mockResolvedValue([alice]),
        markLeaver: vi.fn().mockRejectedValue(refused('KEY_CHANGED')),
      },
    });
    await userEvent.click(
      await screen.findByRole('button', { name: 'Als ausgeschieden markieren' })
    );
    await userEvent.click(screen.getByRole('button', { name: 'Endgültig markieren' }));
    expect(await screen.findByText(/Laden Sie die Liste neu/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    await userEvent.click(screen.getByRole('button', { name: 'Als ausgeschieden markieren' }));
    expect(screen.queryByText(/Laden Sie die Liste neu/)).not.toBeInTheDocument();
  });

  it('sends an expired login back to step-up', async () => {
    render(withKey, {
      repository: {
        leavers: vi.fn().mockResolvedValue([alice]),
        markLeaver: vi.fn().mockRejectedValue(refused('STEP_UP_REQUIRED')),
      },
    });
    await userEvent.click(
      await screen.findByRole('button', { name: 'Als ausgeschieden markieren' })
    );
    await userEvent.click(screen.getByRole('button', { name: 'Endgültig markieren' }));
    expect(await screen.findByText('Identität bestätigen')).toBeInTheDocument();
    expect(screen.queryByText(/Das hat nicht geklappt/)).not.toBeInTheDocument();
  });

  it('says when the directory cannot be trusted', async () => {
    render(withKey, {
      repository: {
        leavers: vi
          .fn()
          .mockRejectedValue(
            new AppError('server', { status: 503, serverCode: 'DIRECTORY_UNAVAILABLE' })
          ),
      },
    });
    expect(await screen.findByText(/nicht erreichbar oder unvollständig/)).toBeInTheDocument();
  });

  it('is offered to org admins only, with or without a recovery key', async () => {
    vi.mocked(hasPermission).mockImplementation(
      (permission) => permission !== 'ssf.configuration.tenant.manage'
    );
    const { recoveryCeremony } = render(withKey);
    expect(await screen.findByText('1234 5678')).toBeInTheDocument();
    expect(screen.queryByText('Ausgeschiedene')).not.toBeInTheDocument();
    expect(recoveryCeremony.leavers).not.toHaveBeenCalled();
  });

  it('is shown before any key exists', async () => {
    render({ recoveryKey: null, ceremony: null, lastFailed: null, chain: null });
    expect(await screen.findByText('Ausgeschiedene')).toBeInTheDocument();
  });
});
