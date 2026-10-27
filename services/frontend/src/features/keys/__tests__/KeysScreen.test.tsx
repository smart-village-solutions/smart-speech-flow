import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity, hasFreshStepUp, requestStepUp } from '@/app/auth/keycloak';
import type { ArchiveCrypto, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import { AppError } from '@/core/http/AppError';
import type { RecordingKeysRepository } from '@/domain/recording/recording.repository';
import type { OwnKey } from '@/domain/recording/recording.types';
import { KeysScreen } from '@/features/keys/KeysScreen';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasFreshStepUp: vi.fn(),
  requestStepUp: vi.fn(),
}));

const STRONG = 'kanne wolke ferne tisch blau';
const keys = {
  encPub: new Uint8Array(65),
  sigPub: new Uint8Array(65),
  fingerprint: new Uint8Array(32).fill(0xab),
} as unknown as UnlockedKeys;
const ownKey: OwnKey = {
  encPub: new Uint8Array(65),
  sigPub: new Uint8Array(65),
  blob: '{"v":1}',
  fingerprint: new Uint8Array(32),
  fingerprintDisplay: 'abab abab abab abab abab abab abab abab abab abab',
  createdAt: '2026-10-26T09:00:00+00:00',
};

function render(overrides: { enrolled?: OwnKey | null; enrol?: RecordingKeysRepository['enrol']; unlock?: ArchiveCrypto['unlock'] } = {}) {
  const keyVault = createKeyVault();
  const remember = vi.fn();
  const recordingKeys: RecordingKeysRepository = {
    ownKey: vi.fn().mockResolvedValue(overrides.enrolled ?? null),
    enrol: overrides.enrol ?? vi.fn().mockResolvedValue({ fingerprint: keys.fingerprint, fingerprintDisplay: 'x' }),
  };
  const archiveCrypto: ArchiveCrypto = {
    createKeys: vi.fn().mockResolvedValue({ blob: '{"v":1}', unlocked: keys }),
    unlock: overrides.unlock ?? vi.fn().mockResolvedValue(keys),
  };
  renderWithProviders(<KeysScreen onBack={vi.fn()} onSignOut={vi.fn()} />, {
    locale: 'de',
    services: {
      recordingKeys,
      archiveCrypto,
      keyVault,
      passphraseStrength: { score: async (passphrase) => (passphrase === STRONG ? 4 : 2) },
      resume: { remember, take: () => null },
    },
  });
  return { recordingKeys, archiveCrypto, keyVault, remember };
}

async function typePassphrase(label: string, value: string) {
  await userEvent.type(await screen.findByLabelText(label), value);
}

// Staff screens render in German, as the dashboard does (useScreenLocale('de')).
describe('KeysScreen', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    vi.mocked(hasFreshStepUp).mockReturnValue(true);
    vi.mocked(requestStepUp).mockResolvedValue(undefined);
  });

  it('asks for a fresh MFA login before enrolment, and comes back to this screen', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    const { remember } = render();
    await userEvent.click(await screen.findByRole('button', { name: 'Erneut anmelden' }));
    expect(remember).toHaveBeenCalledWith('keys');
    expect(requestStepUp).toHaveBeenCalled();
  });

  it('refuses a weak or mistyped passphrase without creating keys', async () => {
    const { archiveCrypto } = render();
    await typePassphrase('Passphrase', 'Passwort12345');
    await typePassphrase('Passphrase wiederholen', 'Passwort12345');
    await userEvent.click(screen.getByRole('button', { name: 'Schlüssel erzeugen' }));
    expect(await screen.findByText(/zu leicht zu erraten/)).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText('Passphrase wiederholen'));
    await typePassphrase('Passphrase wiederholen', 'something else entirely');
    await userEvent.click(screen.getByRole('button', { name: 'Schlüssel erzeugen' }));
    expect(await screen.findByText('Die beiden Eingaben stimmen nicht überein.')).toBeInTheDocument();
    expect(archiveCrypto.createKeys).not.toHaveBeenCalled();
  });

  it('enrols, holds the keys unlocked and shows the fingerprint', async () => {
    const { recordingKeys, keyVault } = render();
    await typePassphrase('Passphrase', STRONG);
    await typePassphrase('Passphrase wiederholen', STRONG);
    await userEvent.click(screen.getByRole('button', { name: 'Schlüssel erzeugen' }));
    expect(await screen.findByText('abab abab abab abab abab abab abab abab abab abab')).toBeInTheDocument();
    expect(recordingKeys.enrol).toHaveBeenCalledWith(keys, '{"v":1}');
    expect(keyVault.current()).toBe(keys);
  });

  it('falls back to the step-up prompt when the gateway asks for it', async () => {
    render({ enrol: vi.fn().mockRejectedValue(new AppError('validation', { status: 403, serverCode: 'STEP_UP_REQUIRED' })) });
    await typePassphrase('Passphrase', STRONG);
    await typePassphrase('Passphrase wiederholen', STRONG);
    await userEvent.click(screen.getByRole('button', { name: 'Schlüssel erzeugen' }));
    expect(await screen.findByRole('button', { name: 'Erneut anmelden' })).toBeInTheDocument();
  });

  it('unlocks an enrolled key, reports a wrong passphrase, and locks again', async () => {
    const unlock = vi.fn().mockRejectedValueOnce(new Error('wrong')).mockResolvedValue(keys);
    const { keyVault } = render({ enrolled: ownKey, unlock });
    await typePassphrase('Passphrase', 'wrong one');
    await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
    expect(await screen.findByText('Diese Passphrase öffnet die Schlüssel nicht.')).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText('Passphrase'));
    await typePassphrase('Passphrase', STRONG);
    await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
    await waitFor(() => expect(keyVault.current()).toBe(keys));
    await userEvent.click(screen.getByRole('button', { name: 'Sperren' }));
    expect(keyVault.current()).toBeNull();
    expect(await screen.findByRole('button', { name: 'Entsperren' })).toBeInTheDocument();
  });
});
