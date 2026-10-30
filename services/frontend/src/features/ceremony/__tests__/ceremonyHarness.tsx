import { vi } from 'vitest';
import type { ArchiveCrypto, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { CeremonyCrypto, PaperDevice } from '@/core/crypto/ceremony-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import { createPaperDeviceHolder } from '@/core/crypto/paper-device-holder';
import type { RecoveryCeremonyRepository } from '@/domain/recovery/recovery.repository';
import type { Ceremony, CeremonyState, RecoveryKey } from '@/domain/recovery/recovery.types';
import { CeremonyScreen } from '@/features/ceremony/CeremonyScreen';
import { renderWithProviders } from '@/test/renderWithProviders';

/** The ceremony screen with every port faked; each test file mocks keycloak itself. */
export const MANAGE = 'ssf.configuration.tenant.manage';
export const point = (fill: number) => new Uint8Array(65).fill(fill);
export const keys = {
  encPub: point(1),
  sigPub: point(2),
  fingerprint: new Uint8Array(32),
  encPrivate: {} as CryptoKey,
  sigPrivate: {} as CryptoKey,
} as UnlockedKeys;

export function ceremony(overrides: Partial<Ceremony> = {}): Ceremony {
  return {
    ceremonyId: '0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a',
    k: 2,
    status: 'dealing',
    startedBy: 'olga',
    expiresAt: '2026-10-27T09:00:00+00:00',
    gatewayKeys: [],
    participants: [
      {
        holderIndex: 1,
        holderRef: 'anna',
        kind: 'custodian',
        displayName: 'Anna',
        encPub: point(1),
        sigPub: point(2),
        fingerprint: new Uint8Array(32),
      },
      {
        holderIndex: 2,
        holderRef: 'bernd',
        kind: 'custodian',
        displayName: 'Bernd',
        encPub: point(3),
        sigPub: point(4),
        fingerprint: new Uint8Array(32),
      },
      {
        holderIndex: 3,
        holderRef: 'carla',
        kind: 'custodian',
        displayName: 'Carla',
        encPub: point(5),
        sigPub: point(6),
        fingerprint: new Uint8Array(32),
      },
    ],
    dealings: [],
    confirmed: [],
    paperConfirmed: false,
    transcriptHash: null,
    kind: 'generation',
    recoveryKeyId: null,
    previousTranscript: null,
    dealers: [],
    ...overrides,
  };
}

export function render(
  state: CeremonyState,
  overrides: {
    repository?: Partial<RecoveryCeremonyRepository>;
    crypto?: Partial<CeremonyCrypto>;
    archive?: Partial<ArchiveCrypto>;
    unlocked?: boolean;
    device?: boolean;
  } = {}
) {
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
    startResharing: vi.fn().mockResolvedValue(ceremony()),
    dealer: vi.fn(),
    paperDeal: vi.fn().mockResolvedValue(undefined),
    leavers: vi.fn().mockResolvedValue([]),
    markLeaver: vi.fn().mockResolvedValue(undefined),
    ...overrides.repository,
  };
  const device: PaperDevice = {
    privateKey: {} as CryptoKey,
    publicKey: point(9),
    fingerprint: new Uint8Array(32),
  };
  const ceremonyCrypto: CeremonyCrypto = {
    fingerprints: vi
      .fn()
      .mockImplementation(
        async (facts) =>
          new Map(
            facts.participants.map((p: { holderIndex: number }) => [
              p.holderIndex,
              new Uint8Array(32).fill(0xab),
            ])
          )
      ),
    deal: vi
      .fn()
      .mockResolvedValue({
        commitments: [],
        proof: { c: 1n, s: 2n },
        signature: new Uint8Array(64),
        subshares: new Map(),
      }),
    receive: vi.fn(),
    confirm: vi.fn(),
    createPaperDevice: vi.fn().mockResolvedValue(device),
    ...overrides.crypto,
  };
  const keyVault = createKeyVault();
  if (overrides.unlocked) keyVault.hold(keys);
  const paperDevice = createPaperDeviceHolder();
  if (overrides.device) paperDevice.hold(device);
  const remember = vi.fn();
  const onOpenKeys = vi.fn();
  renderWithProviders(
    <CeremonyScreen onBack={vi.fn()} onOpenKeys={onOpenKeys} onSignOut={vi.fn()} />,
    {
      locale: 'de',
      services: {
        recoveryCeremony,
        ceremonyCrypto,
        keyVault,
        paperDevice,
        resume: { remember, take: () => null },
        ...(overrides.archive ? { archiveCrypto: overrides.archive as ArchiveCrypto } : {}),
      },
    }
  );
  return { recoveryCeremony, ceremonyCrypto, paperDevice, device, remember, onOpenKeys };
}

export const noKey = { recoveryKey: null, lastFailed: null, chain: null };

export function activeKey(overrides: Partial<RecoveryKey> = {}): RecoveryKey {
  return {
    keyId: 'k',
    k: 2,
    n: 5,
    mode: 'enhanced',
    transcriptDisplay: '1234 5678',
    activatedAt: '2026-10-26T10:00:00+00:00',
    usableShares: null,
    holdersCeremonyId: 'k',
    holders: [],
    previousHadPaper: false,
    ...overrides,
  };
}
