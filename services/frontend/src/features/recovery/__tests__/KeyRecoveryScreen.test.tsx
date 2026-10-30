import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity, hasFreshStepUp } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import { displayFingerprint } from '@/core/crypto/transcript';
import type { RecoveryRequestsRepository } from '@/domain/recovery/requests.repository';
import type { OwnCandidates, RequestSummary } from '@/domain/recovery/requests.types';
import { KeyRecoveryScreen } from '@/features/recovery/KeyRecoveryScreen';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasFreshStepUp: vi.fn(),
}));

const k = de.admin.keyRecovery;
const R1 = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const C1 = '1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5';
const keys = {
  fingerprint: new Uint8Array(32).fill(0x2a),
  sigPrivate: {} as CryptoKey,
} as unknown as UnlockedKeys;

const candidate = {
  conversationId: C1,
  startedAt: '2026-10-20T10:00:00+00:00',
  endedAt: '2026-10-20T10:20:00+00:00',
  retentionUntil: 'x',
  legalHold: false,
  incomplete: false,
  keyIds: ['k1', 'k2'],
};

const request = (status: RequestSummary['status']): RequestSummary => ({
  requestId: R1,
  kind: 'key_recovery',
  requesterSub: 'alice',
  status,
  reason: 'Forgot my passphrase.',
  createdAt: '2026-10-29T10:00:00+00:00',
  expiresAt: '2026-11-05T10:00:00+00:00',
  conversations: 1,
});

interface Options {
  unlocked?: boolean;
  own?: OwnCandidates;
  requests?: RequestSummary[];
}

function render({ unlocked = true, own, requests = [] }: Options = {}) {
  const keyVault = createKeyVault();
  if (unlocked) keyVault.hold(keys);
  const recoveryRequests = {
    requests: vi.fn().mockResolvedValue(requests),
    ownCandidates: vi
      .fn()
      .mockResolvedValue(
        own ?? { conversations: [candidate], remaining: { conversations: 4, keys: 9 } }
      ),
    file: vi.fn().mockResolvedValue([]),
    progress: vi.fn().mockResolvedValue({ ...request('open'), k: 2, decisions: [], scope: [] }),
  } as unknown as RecoveryRequestsRepository;
  const recoveryCrypto = { signRequest: vi.fn().mockResolvedValue(new Uint8Array(64)) };
  const ceremonyCrypto = {
    certifyTrust: vi.fn().mockResolvedValue({ recoveryKeyId: 'rk-1', k: 2 }),
  };
  const archive = { trust: vi.fn().mockResolvedValue({}) };
  const onOpenKeys = vi.fn();
  renderWithProviders(
    <KeyRecoveryScreen onBack={vi.fn()} onOpenKeys={onOpenKeys} onSignOut={vi.fn()} />,
    {
      locale: 'de',
      services: {
        keyVault,
        recoveryRequests,
        recoveryCrypto,
        ceremonyCrypto,
        archive,
        resume: { remember: vi.fn(), take: () => null },
      } as never,
    }
  );
  return { recoveryRequests, recoveryCrypto, onOpenKeys, keyVault };
}

describe('KeyRecoveryScreen', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    vi.mocked(hasFreshStepUp).mockReturnValue(true);
  });

  it('shows the batch, what remains, and the fingerprint of the key in this browser', async () => {
    render();
    expect(await screen.findByText(k.batch.replace('{{count}}', '1'))).toBeInTheDocument();
    expect(screen.getByText(k.remaining.replace('{{conversations}}', '4'))).toBeInTheDocument();
    expect(screen.getByText(displayFingerprint(keys.fingerprint))).toBeInTheDocument();
  });

  it('signs the batch as a key recovery and files it', async () => {
    const { recoveryRequests, recoveryCrypto } = render();
    await userEvent.type(await screen.findByLabelText(k.reason), 'Forgot my passphrase.');
    await userEvent.click(screen.getByRole('button', { name: k.file }));
    await waitFor(() => expect(recoveryRequests.file).toHaveBeenCalled());
    const [signed] = vi.mocked(recoveryCrypto.signRequest).mock.calls[0];
    expect(signed.kind).toBe('key_recovery');
    expect(signed.scope).toEqual([
      { conversationId: C1, keyId: 'k1' },
      { conversationId: C1, keyId: 'k2' },
    ]);
    expect(vi.mocked(recoveryRequests.file).mock.calls[0][0].kind).toBe('key_recovery');
  });

  it('offers no batch while a key recovery is open, and lists it', async () => {
    const { recoveryRequests } = render({ requests: [request('open')] });
    expect(await screen.findByText(de.admin.recovery.kind.key_recovery)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: k.file })).not.toBeInTheDocument();
    expect(recoveryRequests.ownCandidates).not.toHaveBeenCalled();
  });

  it('offers the next request once one completed', async () => {
    render({ requests: [request('completed')] });
    expect(await screen.findByRole('button', { name: k.next })).toBeInTheDocument();
  });

  it('says so when the key opens everything', async () => {
    render({ own: { conversations: [], remaining: { conversations: 0, keys: 0 } } });
    expect(await screen.findByText(k.none)).toBeInTheDocument();
  });

  it('sends a locked user to the keys first', async () => {
    const { onOpenKeys } = render({ unlocked: false });
    await userEvent.click(await screen.findByRole('button', { name: de.admin.recovery.unlock }));
    expect(onOpenKeys).toHaveBeenCalled();
  });

  it('asks for a fresh second factor before the batch', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    render();
    expect(await screen.findByText(k.stepUpBody)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: k.file })).not.toBeInTheDocument();
  });

  it('opens a listed request', async () => {
    const { recoveryRequests } = render({ requests: [request('open')] });
    await userEvent.click(await screen.findByText(de.admin.recovery.kind.key_recovery));
    await waitFor(() => expect(recoveryRequests.progress).toHaveBeenCalledWith(R1));
  });

  it('keeps the fingerprint in view while the custodians call about an open request', async () => {
    render({ requests: [request('open')] });
    expect(await screen.findByText(displayFingerprint(keys.fingerprint))).toBeInTheDocument();
    expect(screen.getByText(k.fingerprintHint)).toBeInTheDocument();
  });

  it('asks for step-up before the unlock, so the redirect wipes no unlocked key', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    render({ unlocked: false });
    expect(await screen.findByText(k.stepUpBody)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: de.admin.recovery.unlock })
    ).not.toBeInTheDocument();
  });

  it('keeps a half-typed reason when the step-up ages during the form', async () => {
    const { keyVault } = render();
    await userEvent.type(await screen.findByLabelText(k.reason), 'Forgot');
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    act(() => keyVault.hold({ ...keys })); // the whole screen renders again
    expect(screen.getByLabelText(k.reason)).toHaveValue('Forgot');
    expect(screen.queryByText(k.stepUpBody)).not.toBeInTheDocument();
  });
});
