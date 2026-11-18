import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ProtectedDetail } from '../TaskDetail';
import { createKeyVault } from '@/core/crypto/key-vault';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { IDS, openedConversation } from '@/features/archive/__tests__/archiveFixture';
import { personalInventory } from '@/test/personalKeys';
import { renderWithProviders } from '@/test/renderWithProviders';

const owner = { tenantId: 'tenant', userSub: 'alice' };
vi.mock('@/app/auth/keycloak', async (original) => ({
  ...(await original<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: () => owner,
}));

function mount({
  held = [],
  available = [1, 2],
  revoked = false,
  mixed = false,
  windows,
}: {
  held?: number[];
  available?: number[];
  revoked?: boolean;
  mixed?: boolean;
  windows?: number[][];
} = {}) {
  const own = (windows ? [1, 2, 3] : [1, 2]).map((keyVersion) => ({
    keyVersion,
    fingerprint: new Uint8Array(32).fill(keyVersion),
    fingerprintDisplay: String(keyVersion),
    blob: 'sealed-' + keyVersion,
    encPub: new Uint8Array(65),
    sigPub: new Uint8Array(65),
    createdAt: '2026-11-18',
  }));
  const inventory = personalInventory(own.at(-1)!, own.slice(0, -1));
  const keyVault = createKeyVault();
  keyVault.reconcile(owner, inventory.versions);
  for (const v of held)
    keyVault.holdVersion(
      owner,
      inventory.versions[v - 1],
      own[v - 1] as unknown as UnlockedKeys,
      keyVault.generation()
    );
  if (revoked) inventory.versions[0].state = 'revoked';
  const open = vi.fn(async (id: string, preference?: readonly number[]) => {
    if (id !== IDS.conversation) throw Error('Unavailable');
    const ordered = preference ?? [];
    const grants = windows ?? (mixed ? [available, [2]] : [available]);
    const selected = grants.map(
      (grant) => ordered.find((v) => grant.includes(v)) ?? Math.max(...grant)
    );
    const required = [...new Set(selected)].sort((a, b) => a - b);
    return {
      ...openedConversation(),
      availableKeyVersions: [...available],
      requiredKeyVersions: required,
      entries: [],
      stamps: [],
      keys: selected.map((v, i) => ({
        keyId: i ? IDS.unwrappedKey : IDS.key,
        epoch: i + 1,
        recoveryWrapped: false,
        wrap: {
          recipientVersion: v,
          recipientFingerprint: own[v - 1].fingerprint,
          creatorRef: 'gateway',
          creatorSignature: new Uint8Array(64),
          blob: 'wrap-' + v,
        },
      })),
    };
  });
  const openWrap = vi.fn(
    async (_wrap: unknown, keys: UnlockedKeys) =>
      ({ version: keys.fingerprint[0] }) as unknown as CryptoKey
  );
  const unlock = vi.fn(async (blob: string, phrase: string) => {
    const version = Number(blob.slice(-1));
    if (phrase !== 'passphrase-' + version) throw Error('Incorrect');
    return own[version - 1];
  });
  renderWithProviders(
    <ProtectedDetail
      target={{ kind: 'recording', id: IDS.conversation }}
      onOpenKeys={vi.fn()}
      onSignOut={vi.fn()}
      onBack={vi.fn()}
      onDone={vi.fn()}
    />,
    {
      locale: 'de',
      services: {
        keyVault,
        archive: { open, gatewaySigners: async () => new Map() },
        archiveCrypto: { unlock, openWrap },
        recordingKeys: {
          passphraseFileEnabled: async () => false,
          versions: async () => inventory,
          version: async (v: number) => own[v - 1],
          reenrolmentImpact: async () => ({ pending: null }),
        },
      } as never,
    }
  );
  return { open, openWrap, unlock };
}

const choice = 'Bevorzugte Schlüsselversion';
const keyField = 'Zugangsschlüssel (Passphrase)';
async function enter(version: number) {
  await userEvent.type(await screen.findByLabelText(keyField), 'passphrase-' + version);
  await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
}

it('retains an already-unlocked superseded grant through access check and viewer read', async () => {
  const { open, openWrap } = mount({ held: [1] });
  await waitFor(() => expect(openWrap).toHaveBeenCalled());
  expect(open.mock.calls.map(([, v]) => v)).toEqual([undefined, [1], [1]]);
  expect(openWrap.mock.calls[0][1].fingerprint[0]).toBe(1);
});

it('defaults to v2 when locked and can open solely with the old passphrase', async () => {
  const { open, openWrap, unlock } = mount();
  expect(await screen.findByLabelText('Schlüsselversion')).toHaveValue('2');
  await userEvent.selectOptions(screen.getByLabelText(choice), '1');
  await waitFor(() => expect(screen.getByLabelText('Schlüsselversion')).toHaveValue('1'));
  await enter(1);
  await waitFor(() => expect(openWrap).toHaveBeenCalled());
  expect(open.mock.calls.slice(1).every(([, v]) => v?.length === 1 && v[0] === 1)).toBe(true);
  expect(unlock).toHaveBeenCalledTimes(1);
});

it('requires v2 for a window with no v1 grant even when v1 is already unlocked', async () => {
  const { open, openWrap } = mount({ held: [1], mixed: true });
  await waitFor(() => expect(open).toHaveBeenCalledWith(IDS.conversation, [1]));
  expect(await screen.findByLabelText('Schlüsselversion')).toHaveValue('2');
  expect(openWrap).not.toHaveBeenCalled();
  await enter(2);
  await waitFor(() => expect(openWrap).toHaveBeenCalledTimes(2));
  expect(openWrap.mock.calls.map(([, key]) => key.fingerprint[0])).toEqual([1, 2]);
  expect(open.mock.calls.at(-1)?.[1]).toEqual([1, 2]);
});

it('rechecks the selected version after unlock and respects a grant removed in the meantime', async () => {
  const available = [1, 2];
  const { openWrap } = mount({ available });
  await userEvent.selectOptions(await screen.findByLabelText(choice), '1');
  await waitFor(() => expect(screen.getByLabelText('Schlüsselversion')).toHaveValue('1'));
  available.shift();
  await enter(1);
  await waitFor(() => expect(screen.getByLabelText('Schlüsselversion')).toHaveValue('2'));
  expect(screen.queryByLabelText(choice)).toBeNull();
  expect(openWrap).not.toHaveBeenCalled();
});

it.each([false, true])(
  'does not offer an older local version without an authorized usable grant (revoked %s)',
  async (revoked) => {
    const { open, openWrap } = mount({ held: [1], available: [2], revoked });
    expect(await screen.findByLabelText('Schlüsselversion')).toHaveValue('2');
    expect(screen.queryByLabelText(choice)).toBeNull();
    expect(open.mock.calls.some(([, v]) => v?.includes(1))).toBe(false);
    expect(openWrap).not.toHaveBeenCalled();
  }
);

it('combines independently held v1 and v2 after an additive v3 transfer to both windows', async () => {
  const { open, openWrap } = mount({
    held: [1, 2],
    available: [1, 2, 3],
    windows: [
      [1, 3],
      [2, 3],
    ],
  });
  await waitFor(() => expect(openWrap).toHaveBeenCalledTimes(2));
  expect(openWrap.mock.calls.map(([, key]) => key.fingerprint[0])).toEqual([1, 2]);
  expect(new Set(open.mock.calls.at(-1)?.[1] as number[])).toEqual(new Set([1, 2]));
  expect(screen.queryByLabelText(keyField)).toBeNull();
});

it('lets the user unlock both earlier versions sequentially without the v3 passphrase', async () => {
  const { open, openWrap, unlock } = mount({
    available: [1, 2, 3],
    windows: [
      [1, 3],
      [2, 3],
    ],
  });
  expect(await screen.findByLabelText('Schlüsselversion')).toHaveValue('3');
  await userEvent.selectOptions(screen.getByLabelText(choice), '1');
  await waitFor(() => expect(screen.getByLabelText('Schlüsselversion')).toHaveValue('1'));
  await enter(1);
  await waitFor(() => expect(screen.getByLabelText('Schlüsselversion')).toHaveValue('3'));
  await userEvent.selectOptions(screen.getByLabelText(choice), '2');
  await waitFor(() => expect(screen.getByLabelText('Schlüsselversion')).toHaveValue('2'));
  await enter(2);
  await waitFor(() => expect(openWrap).toHaveBeenCalledTimes(2));
  expect(unlock.mock.calls.map(([blob]) => blob)).toEqual(['sealed-1', 'sealed-2']);
  expect(open.mock.calls.at(-1)?.[1]).toEqual([2, 1]);
  expect(openWrap.mock.calls.map(([, key]) => key.fingerprint[0])).toEqual([1, 2]);
});
