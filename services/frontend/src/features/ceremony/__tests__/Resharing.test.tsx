import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getAdminIdentity,
  hasFreshStepUp,
  hasPermission,
  requestStepUp,
} from '@/app/auth/keycloak';
import { ShareMismatchError } from '@/core/crypto/ceremony-crypto.port';
import { AppError } from '@/core/http/AppError';
import type {
  Ceremony,
  CeremonyState,
  CurrentHolder,
  ServedChain,
} from '@/domain/recovery/recovery.types';
import { MANAGE, activeKey, ceremony, keys, point, render } from './ceremonyHarness';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasPermission: vi.fn(),
  hasFreshStepUp: vi.fn(),
  requestStepUp: vi.fn(),
}));

const holders: CurrentHolder[] = [
  { holderIndex: 1, holderRef: 'anna', kind: 'custodian', displayName: null, state: 'fresh' },
  { holderIndex: 2, holderRef: 'bernd', kind: 'custodian', displayName: null, state: 'kept' },
  { holderIndex: 3, holderRef: 'carla', kind: 'custodian', displayName: null, state: 'lost' },
  { holderIndex: 4, holderRef: 'paper-1', kind: 'paper', displayName: null, state: 'paper' },
];
const chain: ServedChain = {
  recoveryKeyId: 'k',
  firstTranscriptHash: new Uint8Array(32),
  holdersCeremonyId: 'k',
  holdersTranscriptHash: new Uint8Array(32),
  generations: [],
};
const previousOwner = {
  holderIndex: 1,
  holderRef: 'anna',
  kind: 'custodian' as const,
  displayName: null,
  encPub: point(1),
  sigPub: point(2),
  fingerprint: new Uint8Array(32),
};
const certified = { participants: [previousOwner], holderShares: new Map(), k: 2 };

function resharing(overrides: Partial<Ceremony> = {}): Ceremony {
  return ceremony({
    kind: 'resharing',
    recoveryKeyId: 'k',
    previousTranscript: new Uint8Array(32),
    dealers: [
      { dealerIndex: 1, holderRef: 'anna', kind: 'custodian' },
      { dealerIndex: 4, holderRef: 'paper-1', kind: 'paper' },
    ],
    ...overrides,
  });
}

function withKey(open: Ceremony | null, extra: Partial<CeremonyState> = {}): CeremonyState {
  return { recoveryKey: activeKey({ holders }), ceremony: open, lastFailed: null, chain, ...extra };
}

const dealerKey = {
  dealerIndex: 1,
  encryptedShare: '{"v":1}',
  keyVersion: 1,
  encPub: point(1),
  sigPub: point(2),
  fingerprint: keys.fingerprint,
  fingerprintDisplay: '0000 0000',
  blob: '{"kdf":{}}',
};

describe('changing custodians', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
    vi.mocked(requestStepUp).mockResolvedValue(undefined);
  });

  it('lets an admin choose exactly k current holders, never one whose share is lost', async () => {
    const { recoveryCeremony } = render(withKey(null));
    await userEvent.click(await screen.findByRole('button', { name: 'Verwahrende ändern' }));
    for (const name of ['Anna', 'Bernd', 'Carla'])
      await userEvent.click(await screen.findByText(name));
    const submit = screen.getByRole('button', { name: 'Änderung starten' });
    await userEvent.click(screen.getByText('anna'));
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByText('carla'));
    expect(submit).toBeDisabled();
    expect(screen.getByText('nicht nutzbar')).toHaveClass('text-fg-status-alert');
    await userEvent.click(screen.getByText('Papieranteil paper-1'));
    await userEvent.click(submit);
    await waitFor(() =>
      expect(recoveryCeremony.startResharing).toHaveBeenCalledWith({
        k: 2,
        custodians: ['anna', 'bernd', 'carla'],
        dealers: [1, 4],
        paperDevicePub: null,
        holdersCeremonyId: 'k',
      })
    );
  });

  it('names a refused choice of dealers', async () => {
    render(withKey(null), {
      repository: {
        startResharing: vi
          .fn()
          .mockRejectedValue(
            new AppError('validation', { status: 422, serverCode: 'DEALER_UNUSABLE' })
          ),
      },
    });
    await userEvent.click(await screen.findByRole('button', { name: 'Verwahrende ändern' }));
    for (const name of ['Anna', 'Bernd', 'Carla', 'anna', 'bernd'])
      await userEvent.click(await screen.findByText(name));
    await userEvent.click(screen.getByRole('button', { name: 'Änderung starten' }));
    expect(await screen.findByText(/kann seinen Anteil nicht mehr öffnen/)).toBeInTheDocument();
  });

  it('tells holders of old paper sheets to destroy them, and why a change failed', async () => {
    render(
      withKey(null, {
        recoveryKey: activeKey({ holders, previousHadPaper: true }),
        lastFailed: {
          ceremonyId: 'r',
          reason: 'contribution_invalid',
          endedAt: '2026-10-30T10:00:00+00:00',
        },
      })
    );
    expect(await screen.findByText(/Vernichten Sie die alten Papieranteile/)).toBeInTheDocument();
    expect(
      screen.getByText(/Die bisherigen Verwahrenden behalten ihre Anteile/)
    ).toBeInTheDocument();
  });

  it('waits for the current holders to be certified before anything can be done', async () => {
    render(withKey(resharing()), {
      crypto: { certifyChain: vi.fn().mockReturnValue(new Promise(() => undefined)) },
    });
    expect(
      await screen.findByText(/Protokolle der bisherigen Verwahrenden werden geprüft/)
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Dieses Blatt weitergeben' })
    ).not.toBeInTheDocument();
  });
});

describe('dealing in a resharing', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'anna' });
    vi.mocked(hasPermission).mockImplementation((permission) => permission !== MANAGE);
    vi.mocked(hasFreshStepUp).mockReturnValue(true);
  });

  it('asks for a fresh MFA login before the dealer ticks or unlocks anything', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    const { recoveryCeremony } = render(withKey(resharing()), {
      unlocked: true,
      crypto: { certifyChain: vi.fn().mockResolvedValue(certified) },
    });
    expect(await screen.findByText(/zweiten Faktor/)).toBeInTheDocument();
    expect(screen.queryByText(/· verglichen/)).not.toBeInTheDocument();
    // Each read of the key is audited: none before the fresh login.
    expect(recoveryCeremony.dealer).not.toHaveBeenCalled();
  });

  it('reads no key once it has dealt', async () => {
    const dealt = resharing({
      dealings: [{ dealerIndex: 1, commitments: [], proof: { c: 1n, s: 2n }, signature: null }],
    });
    const { recoveryCeremony } = render(withKey(dealt), {
      unlocked: true,
      crypto: { certifyChain: vi.fn().mockResolvedValue(certified) },
    });
    expect(await screen.findAllByText(/Warten auf die anderen/)).not.toHaveLength(0);
    expect(recoveryCeremony.dealer).not.toHaveBeenCalled();
  });

  it('says why it cannot deal when its key cannot be served', async () => {
    render(withKey(resharing()), {
      unlocked: true,
      repository: {
        dealer: vi
          .fn()
          .mockRejectedValue(
            new AppError('validation', { status: 409, serverCode: 'DEALER_UNUSABLE' })
          ),
      },
      crypto: { certifyChain: vi.fn().mockResolvedValue(certified) },
    });
    expect(await screen.findByText(/kann seinen Anteil nicht mehr öffnen/)).toBeInTheDocument();
  });

  it('sends a dealer with locked keys to unlock them, not to an earlier key', async () => {
    const { onOpenKeys } = render(withKey(resharing()), {
      repository: { dealer: vi.fn().mockResolvedValue(dealerKey) },
      crypto: { certifyChain: vi.fn().mockResolvedValue(certified) },
    });
    // Anna is also a new holder here, so both of her parts offer the same way out.
    const [unlock] = await screen.findAllByRole('button', { name: 'Archivschlüssel öffnen' });
    await userEvent.click(unlock);
    expect(onOpenKeys).toHaveBeenCalled();
    expect(screen.queryByText(/vor der Neueinrichtung hatten/)).not.toBeInTheDocument();
  });

  it('forgets a tick once the fingerprint it was given for changes', async () => {
    let state = withKey(resharing());
    const { recoveryCeremony } = render(state, {
      unlocked: true,
      repository: {
        state: vi.fn().mockImplementation(() => Promise.resolve(state)),
        dealer: vi.fn().mockResolvedValue(dealerKey),
      },
      crypto: { certifyChain: vi.fn().mockResolvedValue(certified) },
    });
    const deal = await screen.findByRole('button', { name: 'Meinen Anteil weitergeben' });
    for (const tick of screen.getAllByText(/· verglichen/)) await userEvent.click(tick);
    expect(deal).toBeEnabled();
    const swapped = resharing();
    swapped.participants = swapped.participants.map((p, i) =>
      i === 0 ? { ...p, fingerprint: new Uint8Array(32).fill(5) } : p
    );
    state = withKey(swapped);
    await recoveryCeremony.state();
    await screen.findByText(/0505 0505/, {}, { timeout: 7000 });
    expect(screen.getByRole('button', { name: 'Meinen Anteil weitergeben' })).toBeDisabled();
  }, 10000);

  it('hands a custodian’s share over only once every new fingerprint is compared', async () => {
    const dealing = {
      commitments: [],
      proof: { c: 1n, s: 2n },
      signature: new Uint8Array(64),
      subshares: new Map(),
    };
    const { recoveryCeremony, ceremonyCrypto } = render(withKey(resharing()), {
      unlocked: true,
      repository: { dealer: vi.fn().mockResolvedValue(dealerKey) },
      crypto: {
        certifyChain: vi.fn().mockResolvedValue(certified),
        openShare: vi.fn().mockResolvedValue(7n),
        dealShare: vi.fn().mockResolvedValue(dealing),
      },
    });
    const deal = await screen.findByRole('button', { name: 'Meinen Anteil weitergeben' });
    const ticks = screen.getAllByText(/· verglichen/);
    for (const tick of ticks.slice(0, -1)) await userEvent.click(tick);
    expect(deal).toBeDisabled();
    await userEvent.click(ticks.at(-1) as HTMLElement);
    await userEvent.click(deal);
    await waitFor(() =>
      expect(recoveryCeremony.deal).toHaveBeenCalledWith(expect.any(String), dealing)
    );
    // The step refetches the ceremony, not the certified chain or the audited key.
    await waitFor(() => expect(recoveryCeremony.state).toHaveBeenCalledTimes(2));
    expect(ceremonyCrypto.certifyChain).toHaveBeenCalledTimes(1);
    expect(recoveryCeremony.dealer).toHaveBeenCalledTimes(1);
    expect(ceremonyCrypto.dealShare).toHaveBeenCalledWith(
      expect.anything(),
      1,
      7n,
      keys.sigPrivate
    );
  });

  it('asks a re-enrolled custodian for the passphrase of the key its share is sealed to', async () => {
    const unlock = vi.fn().mockResolvedValue({ ...keys, fingerprint: new Uint8Array(32).fill(7) });
    render(withKey(resharing()), {
      unlocked: true,
      archive: { unlock },
      repository: {
        dealer: vi
          .fn()
          .mockResolvedValue({ ...dealerKey, fingerprint: new Uint8Array(32).fill(7) }),
      },
      crypto: { certifyChain: vi.fn().mockResolvedValue(certified) },
    });
    expect(await screen.findByText(/vor der Neueinrichtung hatten/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Passphrase'), 'the old one');
    await userEvent.click(screen.getByRole('button', { name: 'Früheren Schlüssel entsperren' }));
    expect(
      await screen.findByRole('button', { name: 'Meinen Anteil weitergeben' })
    ).toBeInTheDocument();
    expect(unlock).toHaveBeenCalledWith(
      dealerKey.blob,
      'the old one',
      expect.anything(),
      expect.anything()
    );
  });

  it('keeps a new holder waiting while the old holders deal', async () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'bernd' });
    render(withKey(resharing()), {
      unlocked: true,
      crypto: { certifyChain: vi.fn().mockResolvedValue(certified) },
    });
    expect(await screen.findByText(/Warten auf die anderen/)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Meinen Beitrag leisten' })
    ).not.toBeInTheDocument();
  });
});

describe('paper sheets dealing on the ceremony device', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'olga' });
    vi.mocked(hasPermission).mockReturnValue(true);
  });

  it('asks for a mistyped sheet again, without aborting, and sends the right one', async () => {
    const dealing = {
      commitments: [],
      proof: { c: 1n, s: 2n },
      signature: null,
      subshares: new Map(),
    };
    const dealShare = vi
      .fn()
      .mockRejectedValueOnce(new ShareMismatchError())
      .mockResolvedValue(dealing);
    const { recoveryCeremony } = render(withKey(resharing()), {
      crypto: { certifyChain: vi.fn().mockResolvedValue(certified), dealShare },
    });
    const input = await screen.findByLabelText('Die 64 Zeichen auf dem Blatt');
    for (const tick of screen.getAllByText(/· verglichen/)) await userEvent.click(tick);
    await userEvent.type(input, 'ab'.repeat(32));
    await userEvent.click(screen.getByRole('button', { name: 'Dieses Blatt weitergeben' }));
    expect(await screen.findByText(/passt nicht zum Anteil dieses Blatts/)).toBeInTheDocument();
    expect(recoveryCeremony.abort).not.toHaveBeenCalled();
    expect(input).toHaveValue('ab'.repeat(32));
    await userEvent.click(screen.getByRole('button', { name: 'Dieses Blatt weitergeben' }));
    await waitFor(() =>
      expect(recoveryCeremony.paperDeal).toHaveBeenCalledWith(expect.any(String), 4, dealing)
    );
    expect(dealShare).toHaveBeenLastCalledWith(
      expect.anything(),
      4,
      BigInt(`0x${'ab'.repeat(32)}`),
      null
    );
  });

  it('refuses what is not 64 hex characters before any crypto runs', async () => {
    const dealShare = vi.fn();
    render(withKey(resharing()), {
      crypto: { certifyChain: vi.fn().mockResolvedValue(certified), dealShare },
    });
    const input = await screen.findByLabelText('Die 64 Zeichen auf dem Blatt');
    for (const tick of screen.getAllByText(/· verglichen/)) await userEvent.click(tick);
    await userEvent.type(input, 'not a share');
    await userEvent.click(screen.getByRole('button', { name: 'Dieses Blatt weitergeben' }));
    expect(await screen.findByText(/passt nicht zum Anteil dieses Blatts/)).toBeInTheDocument();
    expect(dealShare).not.toHaveBeenCalled();
  });
});
