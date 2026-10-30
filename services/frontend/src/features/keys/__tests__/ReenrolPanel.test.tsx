import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity, hasFreshStepUp } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import { AppError } from '@/core/http/AppError';
import type { RecordingKeysRepository } from '@/domain/recording/recording.repository';
import type { OwnKey, Reenrolled } from '@/domain/recording/recording.types';
import { KeysScreen } from '@/features/keys/KeysScreen';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasFreshStepUp: vi.fn(),
  requestStepUp: vi.fn(),
}));

const STRONG = 'kanne wolke ferne tisch blau';
const r = de.admin.keys.reenrol;
const old = { fingerprint: new Uint8Array(32).fill(1) } as unknown as UnlockedKeys;
const fresh = { fingerprint: new Uint8Array(32).fill(2) } as unknown as UnlockedKeys;
const ownKey: OwnKey = {
  encPub: new Uint8Array(65),
  sigPub: new Uint8Array(65),
  blob: '{"v":1}',
  fingerprint: new Uint8Array(32),
  fingerprintDisplay: 'abab abab abab abab abab abab abab abab abab abab',
  createdAt: '2026-10-26T09:00:00+00:00',
  keyVersion: 4,
};
const active: Reenrolled = {
  status: 'active',
  fingerprint: new Uint8Array(32),
  fingerprintDisplay: 'cdcd cdcd cdcd cdcd cdcd cdcd cdcd cdcd cdcd cdcd',
};

interface Options {
  reenrol?: RecordingKeysRepository['reenrol'];
  custodian?: boolean;
  impactFails?: boolean;
}

function render({ reenrol, custodian = false, impactFails = false }: Options = {}) {
  const keyVault = createKeyVault();
  keyVault.hold(old);
  const order: string[] = [];
  const lock = keyVault.lock.bind(keyVault);
  keyVault.lock = () => {
    order.push('lock');
    lock();
  };
  const recordingKeys = {
    ownKey: vi.fn().mockResolvedValue(ownKey),
    enrol: vi.fn(),
    reenrol: reenrol ?? vi.fn().mockResolvedValue(active),
    reenrolmentImpact: impactFails
      ? vi.fn().mockRejectedValue(new Error('down'))
      : vi.fn().mockResolvedValue({ custodian, k: 2, usableAfter: custodian ? 2 : null }),
  };
  const archiveCrypto = {
    createKeys: vi.fn(async () => {
      order.push('create');
      return { blob: '{"v":2}', unlocked: fresh };
    }),
    unlock: vi.fn(),
  };
  const onOpenKeyRecovery = vi.fn();
  renderWithProviders(
    <KeysScreen onBack={vi.fn()} onSignOut={vi.fn()} onOpenKeyRecovery={onOpenKeyRecovery} />,
    {
      locale: 'de',
      services: {
        recordingKeys,
        archiveCrypto,
        keyVault,
        passphraseStrength: { score: async (p: string) => (p === STRONG ? 4 : 2) },
        resume: { remember: vi.fn(), take: () => null },
      } as never,
    }
  );
  return { recordingKeys, archiveCrypto, keyVault, order, onOpenKeyRecovery };
}

async function throughTheWarning() {
  await userEvent.click(await screen.findByRole('button', { name: r.start }));
  await userEvent.click(await screen.findByRole('button', { name: r.continue }));
}

async function submitNewPassphrase() {
  await userEvent.type(await screen.findByLabelText('Passphrase'), STRONG);
  await userEvent.type(screen.getByLabelText('Passphrase wiederholen'), STRONG);
  await userEvent.click(screen.getByRole('button', { name: r.submit }));
}

describe('re-enrolment', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    vi.mocked(hasFreshStepUp).mockReturnValue(true);
  });

  it('warns what is lost before anything else', async () => {
    render();
    await userEvent.click(await screen.findByRole('button', { name: r.start }));
    expect(await screen.findByText(r.warningLocked)).toBeInTheDocument();
    expect(screen.getByText(r.warningRequests)).toBeInTheDocument();
    expect(screen.queryByLabelText('Passphrase wiederholen')).not.toBeInTheDocument();
  });

  it('tells a custodian how many usable shares remain', async () => {
    render({ custodian: true });
    await userEvent.click(await screen.findByRole('button', { name: r.start }));
    const line = r.warningCustodian.replace('{{usable}}', '2').replace('{{k}}', '2');
    expect(await screen.findByText(line)).toBeInTheDocument();
  });

  it('asks for a fresh second factor after the warning', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    render();
    await throughTheWarning();
    expect(await screen.findByRole('button', { name: 'Erneut anmelden' })).toBeInTheDocument();
  });

  it('holds the new key once accepted, replaces the version shown, and offers key recovery', async () => {
    const { recordingKeys, keyVault, order, onOpenKeyRecovery } = render();
    await throughTheWarning();
    await submitNewPassphrase();

    expect(await screen.findByText(r.done)).toBeInTheDocument();
    expect(order).toEqual(['create']);
    expect(recordingKeys.reenrol).toHaveBeenCalledWith(fresh, '{"v":2}', 4);
    expect(keyVault.current()).toBe(fresh);
    await userEvent.click(screen.getByRole('button', { name: de.admin.keyRecovery.open }));
    expect(onOpenKeyRecovery).toHaveBeenCalled();
  });

  it('says to open the email link while confirmation is pending, and keeps the old key', async () => {
    const pending = { ...active, status: 'pending_confirmation' as const };
    const { keyVault } = render({ reenrol: vi.fn().mockResolvedValue(pending) });
    await throughTheWarning();
    await submitNewPassphrase();
    expect(await screen.findByText(r.pending)).toBeInTheDocument();
    expect(keyVault.current()).toBe(old);
  });

  it.each([
    ['KEY_CHANGED', r.changed],
    ['CEREMONY_IN_PROGRESS', r.ceremony],
  ])('names the refusal %s', async (code, message) => {
    const refused = new AppError('validation', { status: 409, serverCode: code });
    const { keyVault } = render({ reenrol: vi.fn().mockRejectedValue(refused) });
    await throughTheWarning();
    await submitNewPassphrase();
    await waitFor(() => expect(screen.getByText(message)).toBeInTheDocument());
    // Review point 3: a refusal costs no unlock.
    expect(keyVault.current()).toBe(old);
  });

  it('offers no way on when the cost of a new key cannot be read', async () => {
    render({ impactFails: true });
    await userEvent.click(await screen.findByRole('button', { name: r.start }));
    expect(await screen.findByText(de.admin.keys.unavailable)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: r.continue })).toBeDisabled();
  });

  it('keeps the new key on screen when the step-up ages afterwards', async () => {
    const { keyVault } = render();
    await throughTheWarning();
    await submitNewPassphrase();
    expect(await screen.findByText(r.done)).toBeInTheDocument();
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    keyVault.lock(); // any re-render
    expect(await screen.findByText(r.done)).toBeInTheDocument();
  });
});
