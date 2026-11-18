import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { TaskWorkspace } from '../TaskWorkspace';
import { renderWithProviders } from '@/test/renderWithProviders';
import { createKeyVault } from '@/core/crypto/key-vault';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { personalInventory } from '@/test/personalKeys';
import type { Services } from '@/app/providers/services';

const owner = { tenantId: 'tenant-kassel', userSub: 'reviewer' };
vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: () => owner,
  hasPermission: (p: string) => p === 'ssf.recording.review',
  getAdminAccessToken: async () => 'staff-token',
}));
vi.mock('@/features/review/ReviewScreen', () => ({
  ReviewScreen: ({
    verificationId,
    unlocked,
  }: {
    verificationId: string;
    unlocked: UnlockedKeys;
  }) => (
    <p>
      Editing {verificationId} with fingerprint {unlocked.fingerprint[0]}
    </p>
  ),
}));

it('cancels to the filtered inbox and unlocks only the selected assignment version before rechecking access', async () => {
  const stamp = '2026-11-18T12:00:00Z';
  const first = {
    keyVersion: 1,
    encPub: new Uint8Array(65),
    sigPub: new Uint8Array(65),
    fingerprint: new Uint8Array(32).fill(1),
    fingerprintDisplay: 'first',
    createdAt: stamp,
    blob: 'first-sealed',
  };
  const second = {
    ...first,
    keyVersion: 2,
    fingerprint: new Uint8Array(32).fill(2),
    fingerprintDisplay: 'second',
    blob: 'second-sealed',
  };
  const inventory = personalInventory(second, [first]);
  const version = vi.fn(async (v: number) => (v === 1 ? first : second));
  const vault = createKeyVault();
  vault.reconcile(owner, inventory.versions);
  const oldKeys = { fingerprint: first.fingerprint } as UnlockedKeys;
  const newKeys = { fingerprint: second.fingerprint } as UnlockedKeys;
  vault.holdVersion(owner, inventory.versions[1], newKeys, vault.generation());
  const row = { verificationId: 'chosen', status: 'in_review', requestedAt: stamp, openable: true };
  const open = vi.fn(async (id: string) => ({
    record: {
      verificationId: id,
      reviewerSub: owner.userSub,
      status: 'in_review',
      reviewerKeyVersion: 1,
      reviewerFingerprint: first.fingerprint,
    },
    opened: { conversation: { employeeSub: 'employee' } },
  }));
  const unlock = vi.fn(async () => oldKeys);
  renderWithProviders(<TaskWorkspace onSignOut={vi.fn()} />, {
    locale: 'de',
    services: {
      reviews: {
        inbox: async () => [row, { ...row, verificationId: 'other', status: 'awaiting' }],
        open,
      },
      recordingKeys: {
        versions: async () => inventory,
        version,
        passphraseFileEnabled: async () => false,
      },
      keyVault: vault,
      archiveCrypto: { unlock },
    } as unknown as Partial<Services>,
  });
  await userEvent.click(await screen.findByRole('button', { name: 'Meine Prüfungen' }));
  await screen.findAllByRole('button', { name: 'Prüfung öffnen' });
  await userEvent.selectOptions(screen.getByLabelText('Status'), 'in_review');
  await userEvent.click(screen.getByRole('button', { name: 'Prüfung öffnen' }));
  await screen.findByLabelText('Passphrase');
  expect(screen.getByRole('combobox', { name: 'Schlüsselversion' })).toHaveValue('1');
  await userEvent.click(screen.getByRole('button', { name: 'Zurück' }));
  expect(await screen.findByLabelText('Status')).toHaveValue('in_review');
  expect(vault.version(owner, 1)).toBeNull();
  await userEvent.click(screen.getByRole('button', { name: 'Prüfung öffnen' }));
  await userEvent.type(await screen.findByLabelText('Passphrase'), 'historical passphrase');
  const checks = open.mock.calls.length;
  await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
  expect(await screen.findByText('Editing chosen with fingerprint 1')).toBeInTheDocument();
  await waitFor(() => expect(open.mock.calls.length).toBeGreaterThan(checks));
  expect(open.mock.calls.every(([id]) => id === 'chosen')).toBe(true);
  expect(version.mock.calls.every(([v]) => v === 1)).toBe(true);
  expect(unlock).toHaveBeenCalledWith('first-sealed', 'historical passphrase', owner, first);
  expect(vault.current()).toBe(newKeys);
});

it('restores only the signed-in owner’s permitted summary and view choices after a step-up redirect', async () => {
  const id = '20000000-0000-4000-8000-000000000001';
  const filters = { language: '', status: 'approved', order: 'oldest' };
  const memory = {
    owner: JSON.stringify(owner),
    account: false,
    tab: 'reviews',
    target: { kind: 'result', id },
    conversations: { ...filters, status: '' },
    reviews: filters,
  };
  const result = vi.fn(async () => ({
    verification_id: id,
    status: 'approved',
    outcome: 'approved',
    requested_at: '2026-11-18T09:00:00Z',
    decided_at: '2026-11-18T10:00:00Z',
  }));
  const inbox = vi.fn(async () => []);
  renderWithProviders(<TaskWorkspace onSignOut={vi.fn()} />, {
    locale: 'de',
    services: {
      resume: { take: () => JSON.stringify(memory), remember: vi.fn() },
      dashboard: { result, conversations: vi.fn() },
      reviews: { inbox },
    } as unknown as Partial<Services>,
  });
  expect(await screen.findByText(id)).toBeInTheDocument();
  expect(result).toHaveBeenCalledWith(id, expect.any(AbortSignal));
  await userEvent.click(screen.getByRole('button', { name: 'Zurück' }));
  expect(await screen.findByLabelText('Sortierung')).toHaveValue('oldest');
  expect(screen.getByLabelText('Status')).toHaveValue('approved');
});
