import { personalInventory } from '@/test/personalKeys';
import { act, screen, waitFor } from '@testing-library/react';
import { focusManager } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity, hasPermission } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import { AppError } from '@/core/http/AppError';
import type { RecordingKeysRepository } from '@/domain/recording/recording.repository';
import type { OwnKey, PendingReenrolment, Reenrolled } from '@/domain/recording/recording.types';
import { KeysScreen } from '@/features/keys/KeysScreen';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasPermission: vi.fn(),
}));

const STRONG = 'kanne wolke ferne tisch blau';
const r = de.admin.keys.reenrol;
const old = { fingerprint: new Uint8Array(32).fill(1) } as unknown as UnlockedKeys;
const fresh = { fingerprint: new Uint8Array(32).fill(2) } as unknown as UnlockedKeys;
const ownKey: OwnKey = {
  encPub: new Uint8Array(65),
  sigPub: new Uint8Array(65),
  blob: '{"v":1}',
  // The unlocked key's, so the vault stays open until the served key changes.
  fingerprint: new Uint8Array(32).fill(1),
  fingerprintDisplay: 'abab abab abab abab abab abab abab abab abab abab',
  createdAt: '2026-10-26T09:00:00+00:00',
  keyVersion: 4,
};
const sent: Reenrolled = {
  status: 'pending_confirmation',
  fingerprint: new Uint8Array(32),
  fingerprintDisplay: 'cdcd cdcd cdcd cdcd cdcd cdcd cdcd cdcd cdcd cdcd',
};

interface Options {
  reenrol?: RecordingKeysRepository['reenrol'];
  custodian?: boolean;
  impactFails?: boolean;
  pending?: PendingReenrolment | null;
  /** What /keys/me serves once a re-enrolment invalidated it. */
  after?: OwnKey;
}

function render({
  reenrol,
  custodian = false,
  impactFails = false,
  pending = null,
  after,
}: Options = {}) {
  const keyVault = createKeyVault();
  const owner = { tenantId: 'tenant-kassel', userSub: 'alice' };
  const initial = personalInventory(ownKey);
  keyVault.reconcile(owner, initial.versions);
  keyVault.holdVersion(owner, initial.versions[0], old, keyVault.generation());
  const order: string[] = [];
  const lock = keyVault.lock.bind(keyVault);
  keyVault.lock = () => {
    order.push('lock');
    lock();
  };
  const recordingKeys = {
    passphraseFileEnabled: vi.fn().mockResolvedValue(false),
    versions: vi.fn(async () => personalInventory(after ?? ownKey)),
    version: vi.fn(async () => after ?? ownKey),
    ownKey: vi
      .fn()
      .mockResolvedValueOnce(ownKey)
      .mockResolvedValue(after ?? ownKey),
    enrol: vi.fn(),
    reenrol: reenrol ?? vi.fn().mockResolvedValue(sent),
    reenrolmentImpact: impactFails
      ? vi.fn().mockRejectedValue(new Error('down'))
      : vi.fn().mockResolvedValue({ custodian, k: 2, usableAfter: custodian ? 2 : null, pending }),
  };
  const archiveCrypto = {
    createKeys: vi.fn(async () => {
      order.push('create');
      return { blob: '{"v":2}', unlocked: fresh };
    }),
    unlock: vi.fn(),
  };
  renderWithProviders(<KeysScreen onBack={vi.fn()} onSignOut={vi.fn()} />, {
    locale: 'de',
    services: {
      recordingKeys,
      archiveCrypto,
      keyVault,
      passphraseStrength: { score: async (p: string) => (p === STRONG ? 4 : 2) },
      resume: { remember: vi.fn(), take: () => null },
    } as never,
  });
  return { recordingKeys, archiveCrypto, keyVault, order };
}

const newKey = { fingerprint: fresh.fingerprint, fingerprintDisplay: sent.fingerprintDisplay };
const waiting = {
  fingerprintDisplay: sent.fingerprintDisplay,
  expiresAt: '2026-11-02T10:00:00+00:00',
};
const until = r.pendingUntil.replace(
  '{{time}}',
  new Intl.DateTimeFormat('de', { hour: '2-digit', minute: '2-digit' }).format(
    new Date(waiting.expiresAt)
  )
);

function impact(pending: PendingReenrolment | null) {
  return { custodian: false, k: 2, usableAfter: null, pending };
}

function refocus() {
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
}

async function throughTheWarning() {
  await userEvent.click(await screen.findByRole('button', { name: r.start }));
  await userEvent.click(await screen.findByRole('button', { name: r.continue }));
}

async function submitNewPassphrase() {
  await userEvent.type(await screen.findByLabelText('Zugangsschlüssel (Passphrase)'), STRONG);
  await userEvent.type(screen.getByLabelText('Passphrase wiederholen'), STRONG);
  await userEvent.click(screen.getByRole('button', { name: r.submit }));
}

describe('re-enrolment', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
  });

  it.each([
    [[], 'personal'],
    [['ssf.recording.review'], 'review'],
    [['ssf.recording.request'], 'recording'],
    [['ssf.recording.request', 'ssf.recording.review'], 'both'],
  ] as const)(
    'explains version replacement for %j before creating keys',
    async (permissions, copy) => {
      vi.mocked(hasPermission).mockImplementation((p) =>
        (permissions as readonly string[]).includes(p)
      );
      render();
      await userEvent.click(await screen.findByRole('button', { name: r.start }));
      expect(await screen.findByText(de.admin.tasks.replacement[copy])).toBeInTheDocument();
      expect(screen.getByText(de.admin.tasks.contact)).toBeInTheDocument();
      expect(screen.queryByLabelText('Passphrase wiederholen')).not.toBeInTheDocument();
    }
  );

  it('activates the key once its link is confirmed elsewhere, and preserves the old version', async () => {
    const after = { ...ownKey, ...newKey, keyVersion: 5 };
    const { recordingKeys, keyVault, order } = render();
    await throughTheWarning();
    recordingKeys.reenrolmentImpact.mockResolvedValue(impact(waiting));
    await submitNewPassphrase();

    expect(await screen.findByText(until)).toBeInTheDocument();
    expect(order).toEqual(['create']);
    expect(recordingKeys.reenrol).toHaveBeenCalledWith(fresh, '{"v":2}', 4);
    expect(keyVault.current()).toBe(old);

    // The link is opened on a phone; the tablet comes back into focus.
    recordingKeys.reenrolmentImpact.mockResolvedValue(impact(null));
    recordingKeys.versions.mockResolvedValue(personalInventory(after, [ownKey]));
    recordingKeys.version.mockResolvedValue(after);
    refocus();

    await waitFor(() => expect(screen.getByRole('combobox')).toHaveValue('5'));
    expect(keyVault.current()).toBeNull();
    expect(keyVault.version({ tenantId: 'tenant-kassel', userSub: 'alice' }, 4)).toBe(old);
  });

  it('says the link ended when it was declined or lapsed', async () => {
    const { recordingKeys, keyVault } = render();
    await throughTheWarning();
    recordingKeys.reenrolmentImpact.mockResolvedValue(impact(waiting));
    await submitNewPassphrase();
    expect(await screen.findByText(until)).toBeInTheDocument();

    recordingKeys.reenrolmentImpact.mockResolvedValue(impact(null));
    refocus();

    expect(await screen.findByText(r.ended)).toBeInTheDocument();
    expect(keyVault.current()).toBe(old);
  });

  it('says to open the email link while confirmation is pending, and keeps the old key', async () => {
    const pending = sent;
    const { recordingKeys, keyVault } = render({ reenrol: vi.fn().mockResolvedValue(pending) });
    await throughTheWarning();
    // Keep the status read pending so the temporary post-submit message is observable.
    let finishRead!: (value: ReturnType<typeof impact>) => void;
    recordingKeys.reenrolmentImpact.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishRead = resolve;
        })
    );
    await submitNewPassphrase();
    expect(await screen.findByText(r.pending)).toBeInTheDocument();
    expect(keyVault.current()).toBe(old);
    act(() => finishRead(impact(waiting)));
    expect(await screen.findByText(until)).toBeInTheDocument();
  });

  it.each([
    ['KEY_CHANGED', r.changed],
    ['CEREMONY_IN_PROGRESS', r.ceremony],
    ['EMAIL_NOT_VERIFIED', r.emailNotVerified],
    ['MAIL_UNAVAILABLE', r.mailUnavailable],
  ])('names the refusal %s', async (code, message) => {
    const refused = new AppError('validation', { status: 409, serverCode: code });
    const { keyVault } = render({ reenrol: vi.fn().mockRejectedValue(refused) });
    await throughTheWarning();
    await submitNewPassphrase();
    await waitFor(() => expect(screen.getByText(message)).toBeInTheDocument());
    // Review point 3: a refusal costs no unlock.
    expect(keyVault.current()).toBe(old);
  });

  it('keeps the waiting key on screen after the vault locks', async () => {
    const { recordingKeys, keyVault } = render();
    await throughTheWarning();
    recordingKeys.reenrolmentImpact.mockResolvedValue(impact(waiting));
    await submitNewPassphrase();
    expect(await screen.findByText(until)).toBeInTheDocument();
    keyVault.lock(); // any re-render
    expect(await screen.findByText(until)).toBeInTheDocument();
  });

  it('shows a key waiting for its link after a reload, with the deadline', async () => {
    const expiresAt = '2026-11-02T10:00:00+00:00';
    render({
      pending: {
        fingerprintDisplay: 'efef efef efef efef efef efef efef efef efef efef',
        expiresAt,
      },
    });
    const time = new Intl.DateTimeFormat('de', { hour: '2-digit', minute: '2-digit' }).format(
      new Date(expiresAt)
    );
    expect(await screen.findByText(r.pendingUntil.replace('{{time}}', time))).toBeInTheDocument();
    expect(
      screen.getByText('efef efef efef efef efef efef efef efef efef efef')
    ).toBeInTheDocument();
  });

  it('shows the waiting key as soon as the re-enrolment is pending', async () => {
    const waiting = {
      fingerprintDisplay: 'efef efef efef efef efef efef efef efef efef efef',
      expiresAt: '2026-11-02T10:00:00+00:00',
    };
    const pendingResult = sent;
    const { recordingKeys } = render({ reenrol: vi.fn().mockResolvedValue(pendingResult) });
    await throughTheWarning();
    // Only after the warning, which reads the same query on its own mount.
    recordingKeys.reenrolmentImpact.mockResolvedValue({
      custodian: false,
      k: 2,
      usableAfter: null,
      pending: waiting,
    });
    await submitNewPassphrase();
    expect(await screen.findByText(waiting.fingerprintDisplay)).toBeInTheDocument();
  });

  it('shows no waiting key when none is pending', async () => {
    render();
    expect(await screen.findByRole('button', { name: r.start })).toBeInTheDocument();
    expect(screen.queryByText(/efef/)).not.toBeInTheDocument();
  });
});
