import { act, screen, waitFor } from '@testing-library/react';
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
import { passphraseFileText } from '../passphrase-file';
import * as passphraseFiles from '../passphrase-file';

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
  fingerprint: new Uint8Array(32).fill(0xab),
  fingerprintDisplay: 'abab abab abab abab abab abab abab abab abab abab',
  createdAt: '2026-10-26T09:00:00+00:00',
  keyVersion: 1,
};

function render(
  overrides: {
    fileEnabled?: boolean;
    enrolled?: OwnKey | null;
    enrol?: RecordingKeysRepository['enrol'];
    unlock?: ArchiveCrypto['unlock'];
    unlocked?: UnlockedKeys;
  } = {}
) {
  const keyVault = createKeyVault();
  if (overrides.unlocked) keyVault.hold(overrides.unlocked);
  const remember = vi.fn();
  let enrolled = overrides.enrolled ?? null;
  const recordingKeys: RecordingKeysRepository = {
    passphraseFileEnabled: vi.fn().mockResolvedValue(overrides.fileEnabled ?? false),
    ownKey: vi.fn(async () => enrolled),
    enrol:
      overrides.enrol ??
      vi.fn(async () => {
        enrolled = ownKey;
        return { fingerprint: keys.fingerprint, fingerprintDisplay: 'x' };
      }),
    reenrol: vi.fn(),
    reenrolmentImpact: vi
      .fn()
      .mockResolvedValue({ custodian: false, k: null, usableAfter: null, pending: null }),
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
    expect(
      await screen.findByText('Die beiden Eingaben stimmen nicht überein.')
    ).toBeInTheDocument();
    expect(archiveCrypto.createKeys).not.toHaveBeenCalled();
  });

  it('enrols, holds the keys unlocked and shows the fingerprint', async () => {
    const { recordingKeys, keyVault } = render();
    await typePassphrase('Passphrase', STRONG);
    await typePassphrase('Passphrase wiederholen', STRONG);
    await userEvent.click(screen.getByRole('button', { name: 'Schlüssel erzeugen' }));
    expect(
      await screen.findByText('abab abab abab abab abab abab abab abab abab abab')
    ).toBeInTheDocument();
    expect(recordingKeys.enrol).toHaveBeenCalledWith(keys, '{"v":1}');
    expect(keyVault.current()).toBe(keys);
  });

  it('falls back to the step-up prompt when the gateway asks for it', async () => {
    render({
      enrol: vi
        .fn()
        .mockRejectedValue(
          new AppError('validation', { status: 403, serverCode: 'STEP_UP_REQUIRED' })
        ),
    });
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
    expect(
      await screen.findByText('Diese Passphrase öffnet die Schlüssel nicht.')
    ).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText('Passphrase'));
    await typePassphrase('Passphrase', STRONG);
    await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
    await waitFor(() => expect(keyVault.current()).toBe(keys));
    await userEvent.click(screen.getByRole('button', { name: 'Sperren' }));
    expect(keyVault.current()).toBeNull();
    expect(await screen.findByRole('button', { name: 'Entsperren' })).toBeInTheDocument();
  });

  it('asks for a verified email address when the gateway refuses enrolment without one', async () => {
    render({
      enrol: vi
        .fn()
        .mockRejectedValue(
          new AppError('validation', { status: 409, serverCode: 'EMAIL_NOT_VERIFIED' })
        ),
    });
    await typePassphrase('Passphrase', STRONG);
    await typePassphrase('Passphrase wiederholen', STRONG);
    await userEvent.click(screen.getByRole('button', { name: 'Schlüssel erzeugen' }));
    expect(await screen.findByText(/keine bestätigte E-Mail-Adresse/)).toBeInTheDocument();
  });

  it('locks the vault once the served key is no longer the unlocked one', async () => {
    const elsewhere = { ...ownKey, fingerprint: new Uint8Array(32).fill(0xcd), keyVersion: 2 };
    const { keyVault } = render({ enrolled: elsewhere, unlocked: keys });
    await waitFor(() => expect(keyVault.current()).toBeNull());
    expect(await screen.findByRole('button', { name: 'Entsperren' })).toBeInTheDocument();
  });

  it('keeps the vault open while the served key is the unlocked one', async () => {
    const { keyVault } = render({ enrolled: ownKey, unlocked: keys });
    expect(await screen.findByRole('button', { name: 'Sperren' })).toBeInTheDocument();
    expect(keyVault.current()).toBe(keys);
  });
  it('offers no file workflow when disabled', async () => {
    render({ enrolled: ownKey });
    await screen.findByRole('button', { name: 'Entsperren' });
    expect(screen.queryByLabelText('Passphrase aus TXT-Datei laden')).not.toBeInTheDocument();
    await typePassphrase('Passphrase', STRONG);
    await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
    await screen.findByRole('button', { name: 'Sperren' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('offers an explicit local backup after successful unlocking', async () => {
    const download = vi.spyOn(passphraseFiles, 'downloadPassphrase').mockImplementation(() => {});
    render({ enrolled: ownKey, fileEnabled: true });
    await typePassphrase('Passphrase', STRONG);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
    expect(await screen.findByRole('dialog', { name: 'Passphrase sichern' })).toBeInTheDocument();
    expect(download).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'TXT-Datei herunterladen' }));
    expect(download).toHaveBeenCalledWith(STRONG);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    download.mockRestore();
  });

  it('offers backup after creating personal keys', async () => {
    render({ fileEnabled: true });
    await typePassphrase('Passphrase', STRONG);
    await typePassphrase('Passphrase wiederholen', STRONG);
    await userEvent.click(screen.getByRole('button', { name: 'Schlüssel erzeugen' }));
    expect(await screen.findByRole('dialog', { name: 'Passphrase sichern' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Jetzt nicht' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('does not offer backup after an incorrect passphrase', async () => {
    render({
      enrolled: ownKey,
      fileEnabled: true,
      unlock: vi.fn().mockRejectedValue(new Error('wrong')),
    });
    await typePassphrase('Passphrase', 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
    await screen.findByText('Diese Passphrase öffnet die Schlüssel nicht.');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('loads a TXT passphrase locally and unlocks only after confirmation', async () => {
    const { archiveCrypto } = render({ enrolled: ownKey, fileEnabled: true });
    const fileInput = await screen.findByLabelText('Passphrase aus TXT-Datei laden');
    await userEvent.upload(
      fileInput,
      new File([passphraseFileText(STRONG)], 'backup.txt', { type: 'text/plain' })
    );
    await waitFor(() => expect(screen.getByLabelText('Passphrase')).toHaveValue(STRONG));
    expect(archiveCrypto.unlock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
    expect(archiveCrypto.unlock).toHaveBeenCalledWith(
      ownKey.blob,
      STRONG,
      expect.anything(),
      ownKey
    );
  });

  it('rejects malformed imported files without unlocking', async () => {
    const { archiveCrypto } = render({ enrolled: ownKey, fileEnabled: true });
    await userEvent.upload(
      await screen.findByLabelText('Passphrase aus TXT-Datei laden'),
      new File(['wrong format'], 'backup.txt', { type: 'text/plain' })
    );
    expect(
      await screen.findByText(
        'Diese Datei ist keine gültige Passphrase-Sicherung oder ist zu groß.'
      )
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Passphrase')).toHaveValue('');
    expect(archiveCrypto.unlock).not.toHaveBeenCalled();
  });

  it('discards an open backup offer when the vault is locked', async () => {
    const { keyVault } = render({ enrolled: ownKey, fileEnabled: true });
    await typePassphrase('Passphrase', STRONG);
    await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
    await screen.findByRole('dialog', { name: 'Passphrase sichern' });
    act(() => keyVault.lock());
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Passphrase')).toHaveValue('');
  });

  it('allows dismissing backup with Escape without creating a file', async () => {
    const download = vi.spyOn(passphraseFiles, 'downloadPassphrase').mockImplementation(() => {});
    try {
      render({ enrolled: ownKey, fileEnabled: true });
      await typePassphrase('Passphrase', STRONG);
      await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
      await screen.findByRole('dialog', { name: 'Passphrase sichern' });
      await userEvent.keyboard('{Escape}');
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(download).not.toHaveBeenCalled();
    } finally {
      download.mockRestore();
    }
  });
});
