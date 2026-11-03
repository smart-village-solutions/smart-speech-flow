import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity, hasPermission, requestStepUp } from '@/app/auth/keycloak';
import { CeremonyCheckError } from '@/core/crypto/ceremony-crypto.port';
import { AppError } from '@/core/http/AppError';
import type { Ceremony } from '@/domain/recovery/recovery.types';
import { MANAGE, activeKey, ceremony, keys, noKey, point, render } from './ceremonyHarness';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasPermission: vi.fn(),
  requestStepUp: vi.fn(),
}));

function withPaperHolders(open: Ceremony): Ceremony {
  const paper = [4, 5].map((holderIndex) => ({
    holderIndex,
    holderRef: `paper-${holderIndex - 3}`,
    kind: 'paper' as const,
    displayName: null,
    encPub: point(9),
    sigPub: null,
    fingerprint: new Uint8Array(32),
  }));
  return { ...open, participants: [...open.participants, ...paper] };
}

describe('CeremonyScreen', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'anna' });
    vi.mocked(hasPermission).mockImplementation((permission) => permission !== MANAGE);
    vi.mocked(requestStepUp).mockResolvedValue(undefined);
  });

  it('lets the administrator start with paper shares, making this browser the ceremony device', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    const { recoveryCeremony, paperDevice, device } = render({ ...noKey, ceremony: null });
    expect(await screen.findByText(/Dora · noch keine Archivschlüssel/)).toBeInTheDocument();
    const start = screen.getByRole('button', { name: 'Zeremonie starten' });
    await userEvent.click(screen.getByText('Anna'));
    await userEvent.click(screen.getByText('Bernd'));
    expect(start).toBeDisabled();
    await userEvent.click(screen.getByText('Carla'));
    await userEvent.click(start);
    await waitFor(() => expect(recoveryCeremony.start).toHaveBeenCalledWith(2, ['anna', 'bernd', 'carla'], device.publicKey));
    expect(paperDevice.current()).toBe(device);
  });

  it('opens in enhanced mode and starts in standard mode with two recovery approvers', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    const { recoveryCeremony, device } = render({ ...noKey, ceremony: null });
    expect(await screen.findByRole('radio', { name: /Erweiterte Wiederherstellung/ })).toBeChecked();
    await userEvent.click(screen.getByRole('radio', { name: /Standard-Wiederherstellung/ }));
    await userEvent.click(screen.getByText('Anna'));
    await userEvent.click(screen.getByText('Bernd'));
    await userEvent.click(screen.getByRole('button', { name: 'Zeremonie starten' }));
    await waitFor(() => expect(recoveryCeremony.start).toHaveBeenCalledWith(1, ['anna', 'bernd'], device.publicKey));
  });

  it('applies the recovery mode Studio sets instead of offering a choice', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    const studioMode = vi.fn().mockResolvedValue('standard');
    const { recoveryCeremony, device } = render({ ...noKey, ceremony: null }, { repository: { studioMode } });
    expect(await screen.findByText('In Studio festgelegt')).toBeInTheDocument();
    const fixed = screen.getByRole('radio', { name: /Standard-Wiederherstellung/ });
    expect(fixed).toBeChecked();
    expect(fixed).toBeDisabled();
    expect(screen.getAllByRole('radio')).toHaveLength(1);
    await userEvent.click(screen.getByText('Anna'));
    await userEvent.click(screen.getByText('Bernd'));
    await userEvent.click(screen.getByRole('button', { name: 'Zeremonie starten' }));
    await waitFor(() => expect(recoveryCeremony.start).toHaveBeenCalledWith(1, ['anna', 'bernd'], device.publicKey));
  });

  it('waits for Studio before the ceremony can start', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    const studioMode = vi.fn().mockReturnValue(new Promise(() => {}));
    render({ ...noKey, ceremony: null }, { repository: { studioMode } });
    for (const name of ['Anna', 'Bernd', 'Carla']) await userEvent.click(await screen.findByText(name));
    expect(screen.getByRole('button', { name: 'Zeremonie starten' })).toBeDisabled();
  });

  it('offers the choice when Studio cannot be read', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    const studioMode = vi.fn().mockRejectedValue(new AppError('server', { status: 503, serverCode: 'STUDIO_UNAVAILABLE' }));
    render({ ...noKey, ceremony: null }, { repository: { studioMode } });
    await waitFor(() => expect(studioMode).toHaveBeenCalled());
    expect(await screen.findAllByRole('radio')).toHaveLength(2);
    expect(screen.queryByText('In Studio festgelegt')).not.toBeInTheDocument();
  });

  it('asks for a fresh MFA login and comes back to the ceremony', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    const stepUp = new AppError('validation', { status: 403, serverCode: 'STEP_UP_REQUIRED' });
    const { remember } = render({ ...noKey, ceremony: null }, { repository: { start: vi.fn().mockRejectedValue(stepUp) } });
    for (const name of ['Anna', 'Bernd', 'Carla']) await userEvent.click(await screen.findByText(name));
    await userEvent.click(screen.getByRole('button', { name: 'Zeremonie starten' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Erneut anmelden' }));
    expect(remember).toHaveBeenCalledWith('ceremony');
  });

  it('tells a custodian without a ceremony to wait for the administrator', async () => {
    render({ ...noKey, ceremony: null });
    expect(await screen.findByText(/Die Organisationsverwaltung startet die Zeremonie/)).toBeInTheDocument();
  });

  it('sends a custodian with locked keys to unlock them first', async () => {
    const { onOpenKeys } = render({ ...noKey, ceremony: ceremony() });
    await userEvent.click(await screen.findByRole('button', { name: 'Archivschlüssel öffnen' }));
    expect(onOpenKeys).toHaveBeenCalled();
  });

  it('deals only after the custodian attests the fingerprint comparison', async () => {
    const { ceremonyCrypto, recoveryCeremony } = render({ ...noKey, ceremony: ceremony() }, { unlocked: true });
    expect(await screen.findAllByText('abab abab abab abab abab abab abab abab abab abab')).toHaveLength(3);
    const deal = screen.getByRole('button', { name: 'Beitrag abgeben' });
    expect(deal).toBeDisabled();
    await userEvent.click(screen.getByText(/jeden Fingerabdruck oben persönlich/));
    await userEvent.click(deal);
    await waitFor(() => expect(recoveryCeremony.deal).toHaveBeenCalled());
    expect(ceremonyCrypto.deal).toHaveBeenCalledWith(expect.objectContaining({ tenantId: 'tenant-kassel', k: 2 }), 1, keys.sigPrivate);
  });

  it('aborts the ceremony when a check fails, naming the fault', async () => {
    const open = ceremony({ status: 'confirming', transcriptHash: new Uint8Array(32) });
    const { recoveryCeremony } = render(
      { ...noKey, ceremony: open },
      { unlocked: true, crypto: { receive: vi.fn().mockRejectedValue(new CeremonyCheckError('subshare_invalid')) } }
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Prüfen und unterschreiben' }));
    expect(await screen.findByText(/Eine Prüfung ist fehlgeschlagen \(subshare_invalid\)/)).toBeInTheDocument();
    expect(recoveryCeremony.abort).toHaveBeenCalledWith(open.ceremonyId, 'subshare_invalid');
    expect(recoveryCeremony.confirm).not.toHaveBeenCalled();
  });

  it('aborts rather than sign a zero share when the gateway leaves out this custodian\'s sub-shares', async () => {
    const open = ceremony({ status: 'confirming', transcriptHash: new Uint8Array(32) });
    const received = { shares: new Map<number, bigint>(), transcriptHash: new Uint8Array(32) };
    const { recoveryCeremony, ceremonyCrypto } = render(
      { ...noKey, ceremony: open },
      { unlocked: true, crypto: { receive: vi.fn().mockResolvedValue(received) } }
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Prüfen und unterschreiben' }));
    expect(await screen.findByText(/Eine Prüfung ist fehlgeschlagen \(subshare_invalid\)/)).toBeInTheDocument();
    expect(recoveryCeremony.abort).toHaveBeenCalledWith(open.ceremonyId, 'subshare_invalid');
    expect(ceremonyCrypto.confirm).not.toHaveBeenCalled();
  });

  it('refuses to deal when the gateway lists other keys for this custodian', async () => {
    const swapped = ceremony();
    swapped.participants[0] = { ...swapped.participants[0], encPub: point(7) };
    const { recoveryCeremony } = render({ ...noKey, ceremony: swapped }, { unlocked: true });
    await userEvent.click(await screen.findByText(/jeden Fingerabdruck oben persönlich/));
    await userEvent.click(screen.getByRole('button', { name: 'Beitrag abgeben' }));
    expect(await screen.findByText(/fingerprint_mismatch/)).toBeInTheDocument();
    expect(recoveryCeremony.deal).not.toHaveBeenCalled();
  });

  it('warns the starting device when it has lost its paper key', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    const withPaper = ceremony();
    withPaper.participants.push({ holderIndex: 4, holderRef: 'paper-1', kind: 'paper', displayName: null, encPub: point(9), sigPub: null, fingerprint: new Uint8Array(32) });
    render({ ...noKey, ceremony: withPaper });
    expect(await screen.findByText(/hält den Papierschlüssel nicht mehr/)).toBeInTheDocument();
  });

  it('aborts rather than print a zero sheet when a paper sub-share is missing', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    const open = withPaperHolders(ceremony({ status: 'confirming', transcriptHash: new Uint8Array(32) }));
    const received = { shares: new Map([[4, 7n]]), transcriptHash: new Uint8Array(32) };
    const { recoveryCeremony } = render(
      { ...noKey, ceremony: open },
      { device: true, crypto: { receive: vi.fn().mockResolvedValue(received) } }
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Prüfen und Papieranteile erzeugen' }));
    expect(await screen.findByText(/Eine Prüfung ist fehlgeschlagen \(subshare_invalid\)/)).toBeInTheDocument();
    expect(recoveryCeremony.abort).toHaveBeenCalledWith(open.ceremonyId, 'subshare_invalid');
    expect(screen.queryByRole('button', { name: 'Drucken' })).not.toBeInTheDocument();
  });

  it('does not call the device lost once its paper shares are printed and confirmed', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    const printed = withPaperHolders(ceremony({ status: 'confirming', transcriptHash: new Uint8Array(32), paperConfirmed: true }));
    render({ ...noKey, ceremony: printed });
    expect(await screen.findByText(/Die Papiersicherung ist abgeschlossen/)).toBeInTheDocument();
    expect(screen.queryByText(/hält den Papierschlüssel nicht mehr/)).not.toBeInTheDocument();
  });

  it('says so when an abort fails, and keeps the paper key for another try', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    const { paperDevice, device } = render(
      { ...noKey, ceremony: withPaperHolders(ceremony()) },
      { device: true, repository: { abort: vi.fn().mockRejectedValue(new AppError('network')) } }
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Zeremonie abbrechen' }));
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Zeremonie abbrechen' }));
    expect(await screen.findByText(/konnte nicht abgebrochen werden/)).toBeInTheDocument();
    expect(paperDevice.current()).toBe(device);
  });

  it('tells every participant why the last ceremony ended', async () => {
    render({
      ...noKey,
      ceremony: null,
      lastFailed: { ceremonyId: 'c-1', reason: 'proof_invalid', endedAt: '2026-10-26T10:00:00+00:00' },
    });
    expect(await screen.findByText(/Die letzte Zeremonie wurde abgebrochen \(proof_invalid\)/)).toBeInTheDocument();
    expect(screen.getByText(/Die Organisationsverwaltung startet die Zeremonie/)).toBeInTheDocument();
  });

  it('shows the active recovery key', async () => {
    render({
      recoveryKey: activeKey(),
      ceremony: null,
      lastFailed: null,
      chain: null,
    });
    expect(await screen.findByText(/Erweiterte Wiederherstellung: 2 Freigaben nötig/)).toBeInTheDocument();
    expect(screen.getByText('Anteile insgesamt: 5')).toBeInTheDocument();
    expect(screen.queryByText(/Freigabebereite Personen/)).not.toBeInTheDocument();
  });

  it('warns when no more than k custodian shares are still usable', async () => {
    render({
      recoveryKey: activeKey({ n: 3, usableShares: 2 }),
      ceremony: null,
      lastFailed: null,
      chain: null,
    });
    const line = await screen.findByText('Freigabebereite Personen: 2 · Nötige Freigaben: 2');
    expect(line).toHaveClass('text-fg-status-alert');
  });

  it('flags a key whose mode differs from the one Studio sets', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    const studioMode = vi.fn().mockResolvedValue('standard');
    render({ recoveryKey: activeKey(), ceremony: null, lastFailed: null, chain: null }, { repository: { studioMode } });
    expect(await screen.findByText(/entspricht nicht dem in Studio festgelegten Modus/)).toBeInTheDocument();
  });

  it('never asks Studio on behalf of a custodian', async () => {
    const studioMode = vi.fn().mockResolvedValue('standard');
    render({ recoveryKey: activeKey(), ceremony: null, lastFailed: null, chain: null }, { repository: { studioMode } });
    expect(await screen.findByText(/Erweiterte Wiederherstellung/)).toBeInTheDocument();
    expect(studioMode).not.toHaveBeenCalled();
  });

  it('raises no flag when the key matches Studio', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    const studioMode = vi.fn().mockResolvedValue('enhanced');
    render({ recoveryKey: activeKey(), ceremony: null, lastFailed: null, chain: null }, { repository: { studioMode } });
    await waitFor(() => expect(studioMode).toHaveBeenCalled());
    // A flag would follow the answer within milliseconds; give it time to appear.
    await expect(
      screen.findByText(/entspricht nicht dem in Studio festgelegten Modus/, {}, { timeout: 300 })
    ).rejects.toThrow();
  });

  it('reads correctly for a standard key with a single approval', async () => {
    render({
      recoveryKey: activeKey({ k: 1, n: 2, mode: 'standard', usableShares: 2 }),
      ceremony: null,
      lastFailed: null,
      chain: null,
    });
    expect(await screen.findByText(/Standard-Wiederherstellung: Eine Freigabe genügt/)).toBeInTheDocument();
    expect(screen.getByText('Freigabebereite Personen: 2 · Nötige Freigaben: 1')).toHaveClass('text-fg-muted');
  });
});
