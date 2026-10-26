import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity, hasPermission, requestStepUp } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { CeremonyCheckError, type CeremonyCrypto, type PaperDevice } from '@/core/crypto/ceremony-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import { createPaperDeviceHolder } from '@/core/crypto/paper-device-holder';
import { AppError } from '@/core/http/AppError';
import type { RecoveryCeremonyRepository } from '@/domain/recovery/recovery.repository';
import type { Ceremony, CeremonyState } from '@/domain/recovery/recovery.types';
import { CeremonyScreen } from '@/features/ceremony/CeremonyScreen';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasPermission: vi.fn(),
  requestStepUp: vi.fn(),
}));

const MANAGE = 'ssf.configuration.tenant.manage';
const point = (fill: number) => new Uint8Array(65).fill(fill);
const keys = {
  encPub: point(1),
  sigPub: point(2),
  fingerprint: new Uint8Array(32),
  encPrivate: {} as CryptoKey,
  sigPrivate: {} as CryptoKey,
} as UnlockedKeys;

function ceremony(overrides: Partial<Ceremony> = {}): Ceremony {
  return {
    ceremonyId: '0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a',
    k: 2,
    status: 'dealing',
    startedBy: 'olga',
    expiresAt: '2026-10-27T09:00:00+00:00',
    gatewayKeys: [],
    participants: [
      { holderIndex: 1, holderRef: 'anna', kind: 'custodian', displayName: 'Anna', encPub: point(1), sigPub: point(2), fingerprint: new Uint8Array(32) },
      { holderIndex: 2, holderRef: 'bernd', kind: 'custodian', displayName: 'Bernd', encPub: point(3), sigPub: point(4), fingerprint: new Uint8Array(32) },
      { holderIndex: 3, holderRef: 'carla', kind: 'custodian', displayName: 'Carla', encPub: point(5), sigPub: point(6), fingerprint: new Uint8Array(32) },
    ],
    dealings: [],
    confirmed: [],
    paperConfirmed: false,
    transcriptHash: null,
    ...overrides,
  };
}

function render(state: CeremonyState, overrides: { repository?: Partial<RecoveryCeremonyRepository>; crypto?: Partial<CeremonyCrypto>; unlocked?: boolean } = {}) {
  const recoveryCeremony: RecoveryCeremonyRepository = {
    state: vi.fn().mockResolvedValue(state),
    candidates: vi.fn().mockResolvedValue([
      { sub: 'anna', displayName: 'Anna', fingerprintDisplay: 'aaaa' },
      { sub: 'bernd', displayName: 'Bernd', fingerprintDisplay: 'bbbb' },
      { sub: 'carla', displayName: 'Carla', fingerprintDisplay: 'cccc' },
      { sub: 'dora', displayName: 'Dora', fingerprintDisplay: null },
    ]),
    start: vi.fn().mockResolvedValue(ceremony()),
    deal: vi.fn().mockResolvedValue(undefined),
    subshares: vi.fn().mockResolvedValue(new Map()),
    confirm: vi.fn().mockResolvedValue(undefined),
    confirmPaper: vi.fn().mockResolvedValue(undefined),
    abort: vi.fn().mockResolvedValue(undefined),
    ...overrides.repository,
  };
  const device: PaperDevice = { privateKey: {} as CryptoKey, publicKey: point(9), fingerprint: new Uint8Array(32) };
  const ceremonyCrypto: CeremonyCrypto = {
    fingerprints: vi.fn().mockImplementation(async (facts) => new Map(facts.participants.map((p: { holderIndex: number }) => [p.holderIndex, new Uint8Array(32).fill(0xab)]))),
    deal: vi.fn().mockResolvedValue({ commitments: [], proof: { c: 1n, s: 2n }, signature: new Uint8Array(64), subshares: new Map() }),
    receive: vi.fn(),
    confirm: vi.fn(),
    createPaperDevice: vi.fn().mockResolvedValue(device),
    ...overrides.crypto,
  };
  const keyVault = createKeyVault();
  if (overrides.unlocked) keyVault.hold(keys);
  const paperDevice = createPaperDeviceHolder();
  const remember = vi.fn();
  const onOpenKeys = vi.fn();
  renderWithProviders(<CeremonyScreen onBack={vi.fn()} onOpenKeys={onOpenKeys} onSignOut={vi.fn()} />, {
    locale: 'de',
    services: { recoveryCeremony, ceremonyCrypto, keyVault, paperDevice, resume: { remember, take: () => null } },
  });
  return { recoveryCeremony, ceremonyCrypto, paperDevice, device, remember, onOpenKeys };
}

const noKey = { recoveryKey: null };

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

  it('shows the active recovery key', async () => {
    render({
      recoveryKey: { keyId: 'k', k: 2, n: 5, mode: 'enhanced', transcriptDisplay: '1234 5678', activatedAt: '2026-10-26T10:00:00+00:00' },
      ceremony: null,
    });
    expect(await screen.findByText(/2 von 5 Anteilen öffnen gemeinsam ein Gespräch/)).toBeInTheDocument();
  });
});
