import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getAdminIdentity,
  hasAcceptedStepUp,
  hasFreshStepUp,
  stepUpSecondsLeft,
} from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import { RecoveryCheckError } from '@/core/crypto/recovery-crypto.port';
import { RecoveryRefusedError } from '@/domain/recovery/requests.repository';
import { displayFingerprint } from '@/core/crypto/transcript';
import type { RecoveryRequestsRepository } from '@/domain/recovery/requests.repository';
import type { ApprovalDetail } from '@/domain/recovery/requests.types';
import { RecoveryApprovalsScreen } from '@/features/recovery/RecoveryApprovalsScreen';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasFreshStepUp: vi.fn(),
  hasAcceptedStepUp: vi.fn(),
  stepUpSecondsLeft: vi.fn(),
}));

const keys = { fingerprint: new Uint8Array(32) } as unknown as UnlockedKeys;
const R1 = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const r = de.admin.recovery;

function detail(encFill = 4): ApprovalDetail {
  return {
    requestId: R1,
    kind: 'key_recovery',
    recoveryKeyId: 'rk-1',
    requesterSub: 'sam',
    requesterName: 'Sam Supervisor',
    requesterEncPub: new Uint8Array(65).fill(encFill),
    requesterSigPub: new Uint8Array(65).fill(5),
    reason: 'Employee left.',
    createdAt: '2026-10-29T10:00:00+00:00',
    expiresAt: '2026-11-05T10:00:00+00:00',
    requestSignature: new Uint8Array(64),
    signedScope: [],
    keys: [],
    holderIndex: 2,
    attempt: 1,
    encryptedShare: '{}',
  };
}

interface RenderOptions {
  detail?: ApprovalDetail;
  approve?: () => Promise<unknown>;
  locked?: boolean;
  shareStale?: boolean;
}

function render(options: RenderOptions = {}) {
  const keyVault = createKeyVault();
  if (!options.locked) keyVault.hold(keys);
  const recoveryRequests = {
    approvals: vi.fn().mockResolvedValue({
      requests: options.shareStale
        ? []
        : [
            {
              requestId: R1,
              kind: 'key_recovery',
              requesterSub: 'sam',
              status: 'open',
              reason: 'Employee left.',
              createdAt: 'a',
              expiresAt: 'b',
              conversations: 1,
            },
          ],
      shareStale: options.shareStale ?? false,
    }),
    approval: vi.fn().mockResolvedValue(options.detail ?? detail()),
    approve: vi.fn().mockResolvedValue(undefined),
    decline: vi.fn().mockResolvedValue(undefined),
  } as unknown as RecoveryRequestsRepository;
  // Echoes the served encryption key into the fingerprint, so a swapped key shows.
  const recoveryCrypto = {
    fingerprintOf: vi.fn((_t: string, _s: string, k: { encPub: Uint8Array }) =>
      Promise.resolve(new Uint8Array(32).fill(k.encPub[0]))
    ),
    approve: vi.fn(
      options.approve ??
        (() => Promise.resolve({ partials: new Map(), signature: new Uint8Array(64) }))
    ),
  };
  const ceremonyCrypto = { certifyChain: vi.fn().mockResolvedValue({}) };
  const archive = { trust: vi.fn().mockResolvedValue({}) };
  renderWithProviders(
    <RecoveryApprovalsScreen onBack={vi.fn()} onOpenKeys={vi.fn()} onSignOut={vi.fn()} />,
    {
      locale: 'de',
      services: { keyVault, recoveryRequests, recoveryCrypto, ceremonyCrypto, archive } as never,
    }
  );
  return { recoveryRequests, recoveryCrypto };
}

async function openRequest() {
  await userEvent.click(await screen.findByText('sam'));
}

describe('RecoveryApprovalsScreen', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'carol' });
    vi.mocked(hasFreshStepUp).mockReturnValue(true);
    vi.mocked(hasAcceptedStepUp).mockReturnValue(true);
    vi.mocked(stepUpSecondsLeft).mockReturnValue(300);
  });

  it('labels each request with its kind, in the list and in the review', async () => {
    render();
    expect(await screen.findByText(r.kind.key_recovery)).toBeInTheDocument();
    await openRequest();
    expect(await screen.findAllByText(r.kind.key_recovery)).not.toHaveLength(0);
    // A key recovery asks the employee whether they filed it at all (§9.6).
    expect(screen.getByText(r.approve.askFiled)).toBeInTheDocument();
  });

  it('a custodian whose share went stale sees why, and nothing to decide', async () => {
    render({ shareStale: true });
    expect(await screen.findByText(r.error.SHARE_STALE)).toBeInTheDocument();
    expect(screen.queryByText('sam')).not.toBeInTheDocument();
  });

  it('shows how far a long approval got', async () => {
    let report: ((done: number, total: number) => void) | undefined;
    let finish: (() => void) | undefined;
    render({
      approve: (...args: unknown[]) => {
        report = args[4] as typeof report;
        return new Promise((resolve) => {
          finish = () => resolve({ partials: new Map(), signature: new Uint8Array(64) });
        });
      },
    });
    await openRequest();
    await waitFor(() => expect(screen.queryByText('…')).not.toBeInTheDocument());
    await userEvent.click(await screen.findByLabelText(r.approve.confirmed));
    await userEvent.click(screen.getByRole('button', { name: r.approve.action }));
    await waitFor(() => expect(report).toBeDefined());
    // The step-up ages while the approval computes: no redirect may interrupt it.
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    act(() => report?.(50, 120));
    const shown = de.admin.keyRecovery.progress
      .replace('{{done}}', '50')
      .replace('{{total}}', '120');
    expect(await screen.findByText(shown)).toBeInTheDocument();
    expect(screen.queryByText(r.stepUpBody)).not.toBeInTheDocument();
    act(() => finish?.());
  });

  it('shows the fingerprint computed from the served keys', async () => {
    render({ detail: detail(9) });
    await openRequest();
    expect(
      await screen.findByText(displayFingerprint(new Uint8Array(32).fill(9)))
    ).toBeInTheDocument();
  });

  it('approves only after the fingerprint was confirmed', async () => {
    const { recoveryRequests } = render();
    await openRequest();
    const approve = await screen.findByRole('button', { name: r.approve.action });
    await waitFor(() => expect(screen.queryByText('…')).not.toBeInTheDocument());
    expect(approve).toBeDisabled();
    await userEvent.click(screen.getByLabelText(r.approve.confirmed));
    await userEvent.click(approve);
    await waitFor(() => expect(recoveryRequests.approve).toHaveBeenCalled());
  });

  it('a failed check shows its fault and posts nothing', async () => {
    const { recoveryRequests } = render({
      approve: () => Promise.reject(new RecoveryCheckError('not_listed')),
    });
    await openRequest();
    await waitFor(() => expect(screen.queryByText('…')).not.toBeInTheDocument());
    await userEvent.click(await screen.findByLabelText(r.approve.confirmed));
    await userEvent.click(screen.getByRole('button', { name: r.approve.action }));
    expect(await screen.findByText(r.fault.not_listed)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: r.approve.action })).not.toBeInTheDocument();
    expect(recoveryRequests.approve).not.toHaveBeenCalled();
  });

  it('declines with a reason only', async () => {
    const { recoveryRequests } = render();
    await openRequest();
    await userEvent.click(await screen.findByRole('button', { name: r.decline.action }));
    const submit = screen.getByRole('button', { name: r.decline.submit });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText(r.decline.reason), 'Not justified.');
    await userEvent.click(submit);
    await waitFor(() =>
      expect(recoveryRequests.decline).toHaveBeenCalledWith(R1, 'Not justified.')
    );
  });

  it('asks for a fresh second factor before anything is unlocked or computed', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    const { recoveryCrypto } = render();
    await openRequest();
    expect(await screen.findByText(r.stepUpBody)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: r.approve.action })).not.toBeInTheDocument();
    expect(recoveryCrypto.approve).not.toHaveBeenCalled();
  });

  it('a step-up that lapses while the screen is open stops the approval before any check', async () => {
    const { recoveryCrypto, recoveryRequests } = render();
    await openRequest();
    await waitFor(() => expect(screen.queryByText('…')).not.toBeInTheDocument());
    await userEvent.click(await screen.findByLabelText(r.approve.confirmed));
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    await userEvent.click(screen.getByRole('button', { name: r.approve.action }));
    expect(await screen.findByText(r.stepUpBody)).toBeInTheDocument();
    expect(recoveryCrypto.approve).not.toHaveBeenCalled();
    expect(recoveryRequests.approve).not.toHaveBeenCalled();
  });

  it('a locked custodian reads the request and may decline; approving asks to unlock', async () => {
    const { recoveryRequests } = render({ locked: true });
    await openRequest();
    expect(await screen.findByRole('button', { name: r.unlock })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: r.approve.action })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: r.decline.action }));
    await userEvent.type(screen.getByLabelText(r.decline.reason), 'No.');
    await userEvent.click(screen.getByRole('button', { name: r.decline.submit }));
    await waitFor(() => expect(recoveryRequests.decline).toHaveBeenCalledWith(R1, 'No.'));
  });

  it('approves with exactly the fingerprint that was ticked', async () => {
    const { recoveryCrypto } = render({ detail: detail(7) });
    await openRequest();
    await waitFor(() => expect(screen.queryByText('…')).not.toBeInTheDocument());
    await userEvent.click(await screen.findByLabelText(r.approve.confirmed));
    await userEvent.click(screen.getByRole('button', { name: r.approve.action }));
    await waitFor(() => expect(recoveryCrypto.approve).toHaveBeenCalled());
    const [facts] = recoveryCrypto.approve.mock.calls[0] as unknown as [
      { confirmedFingerprint: Uint8Array },
    ];
    expect(Array.from(facts.confirmedFingerprint)).toEqual(Array.from(new Uint8Array(32).fill(7)));
  });

  it('after a refusal it offers to try again, with the detail read anew', async () => {
    const { recoveryRequests } = render({
      approve: () => Promise.reject(new RecoveryRefusedError('SIGNATURE_INVALID')),
    });
    await openRequest();
    await waitFor(() => expect(screen.queryByText('…')).not.toBeInTheDocument());
    await userEvent.click(await screen.findByLabelText(r.approve.confirmed));
    await userEvent.click(screen.getByRole('button', { name: r.approve.action }));
    await userEvent.click(await screen.findByRole('button', { name: r.retry }));
    expect(await screen.findByRole('button', { name: r.approve.action })).toBeInTheDocument();
    expect(recoveryRequests.approval).toHaveBeenCalledTimes(2);
  });
});
