import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity, hasFreshStepUp } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import type { RecoveryRequestsRepository } from '@/domain/recovery/requests.repository';
import type { RequestProgress, RequestSummary } from '@/domain/recovery/requests.types';
import { RecoveryRequestsScreen } from '@/features/recovery/RecoveryRequestsScreen';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasFreshStepUp: vi.fn(),
}));

const keys = {
  fingerprint: new Uint8Array(32),
  sigPrivate: {} as CryptoKey,
} as unknown as UnlockedKeys;
const R1 = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const C1 = '1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5';
const C2 = '2c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5';
const r = de.admin.recovery;

const summary: RequestSummary = {
  requestId: R1,
  requesterSub: 'sam',
  status: 'open',
  reason: 'Employee left.',
  createdAt: '2026-10-29T10:00:00+00:00',
  expiresAt: '2026-11-05T10:00:00+00:00',
  conversations: 2,
};

function progress(decisions: RequestProgress['decisions'] = []): RequestProgress {
  return { ...summary, k: 2, decisions, scope: [] };
}

const decision = (holderIndex: number, rejected = false) => ({
  holderIndex,
  attempt: 1,
  custodianSub: holderIndex === 1 ? 'carol' : 'dave',
  custodianName: holderIndex === 1 ? 'Carol Custodian' : null,
  decision: 'approved' as const,
  reason: null,
  decidedAt: '2026-10-29T11:00:00+00:00',
  rejected,
});

function render(options: { unlocked?: UnlockedKeys | null; progress?: RequestProgress } = {}) {
  const keyVault = createKeyVault();
  if (options.unlocked !== null) keyVault.hold(options.unlocked ?? keys);
  const recoveryRequests = {
    requests: vi.fn().mockResolvedValue([summary]),
    progress: vi.fn().mockResolvedValue(options.progress ?? progress()),
    employees: vi.fn().mockResolvedValue([{ sub: 'alice', displayName: 'Alice Employee' }]),
    candidates: vi.fn().mockResolvedValue([
      {
        conversationId: C1,
        startedAt: '2026-10-20T10:00:00+00:00',
        endedAt: '2026-10-20T10:20:00+00:00',
        retentionUntil: 'x',
        legalHold: false,
        incomplete: false,
        keyIds: ['k1'],
      },
      {
        conversationId: C2,
        startedAt: '2026-10-21T10:00:00+00:00',
        endedAt: '2026-10-21T10:20:00+00:00',
        retentionUntil: 'x',
        legalHold: true,
        incomplete: false,
        keyIds: ['k2', 'k3'],
      },
    ]),
    file: vi.fn().mockResolvedValue([]),
    cancel: vi.fn().mockResolvedValue(undefined),
    partials: vi.fn().mockResolvedValue({ wraps: [], approvals: [] }),
    reject: vi.fn().mockResolvedValue(undefined),
    reportIntegrity: vi.fn().mockResolvedValue(undefined),
  } as unknown as RecoveryRequestsRepository;
  const recoveryCrypto = {
    signRequest: vi.fn().mockResolvedValue(new Uint8Array(64)),
    combine: vi.fn().mockResolvedValue({
      wraps: null,
      rejections: [{ holderIndex: 1, attempt: 1, fault: 'proof_invalid' }],
      integrity: [],
    }),
  };
  const ceremonyCrypto = { certifyTrust: vi.fn().mockResolvedValue({ k: 2 }) };
  const archive = { trust: vi.fn().mockResolvedValue({ recoveryKeyId: 'rk-1' }) };
  const onOpenKeys = vi.fn();
  renderWithProviders(
    <RecoveryRequestsScreen onBack={vi.fn()} onOpenKeys={onOpenKeys} onSignOut={vi.fn()} />,
    {
      locale: 'de',
      services: { keyVault, recoveryRequests, recoveryCrypto, archive, ceremonyCrypto } as never,
    }
  );
  return { recoveryRequests, recoveryCrypto, onOpenKeys };
}

describe('RecoveryRequestsScreen', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'sam' });
    vi.mocked(hasFreshStepUp).mockReturnValue(true);
  });

  it('lists requests without a key, and a new request asks for step-up before the unlock', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    const { recoveryRequests, onOpenKeys } = render({ unlocked: null });
    expect(await screen.findByText(summary.reason)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: r.new.action }));
    expect(await screen.findByText(r.stepUpBody)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: r.unlock })).not.toBeInTheDocument();
    expect(recoveryRequests.employees).not.toHaveBeenCalled();
    expect(onOpenKeys).not.toHaveBeenCalled();
  });

  it('with a fresh step-up but locked keys, a new request asks to unlock', async () => {
    const { onOpenKeys } = render({ unlocked: null });
    await userEvent.click(await screen.findByRole('button', { name: r.new.action }));
    await userEvent.click(await screen.findByRole('button', { name: r.unlock }));
    expect(onOpenKeys).toHaveBeenCalled();
  });

  it('lists requests with their status and opens one with its progress', async () => {
    render({ progress: progress([decision(1), decision(2, true)]) });
    await userEvent.click(await screen.findByText(summary.reason));
    expect(await screen.findByText('1 von 2 Zustimmungen')).toBeInTheDocument();
    expect(screen.getByText(r.decision.rejected)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: r.detail.combine })).not.toBeInTheDocument();
  });

  it('offers to combine once k approvals count', async () => {
    render({ progress: progress([decision(1), decision(2)]) });
    await userEvent.click(await screen.findByText(summary.reason));
    expect(await screen.findByRole('button', { name: r.detail.combine })).toBeInTheDocument();
  });

  it('names the custodian whose partial was rejected and keeps waiting', async () => {
    const { recoveryRequests } = render({ progress: progress([decision(1), decision(2)]) });
    await userEvent.click(await screen.findByText(summary.reason));
    await userEvent.click(await screen.findByRole('button', { name: r.detail.combine }));
    expect(await screen.findByText(r.combine.waiting)).toBeInTheDocument();
    expect(
      screen.getByText('Das Teilergebnis von Carol Custodian war ungültig und wurde verworfen.')
    ).toBeInTheDocument();
    expect(recoveryRequests.reject).toHaveBeenCalledWith(R1, {
      holderIndex: 1,
      attempt: 1,
      fault: 'proof_invalid',
    });
  });

  it('cancels an open request', async () => {
    const { recoveryRequests } = render();
    await userEvent.click(await screen.findByText(summary.reason));
    await userEvent.click(await screen.findByRole('button', { name: r.detail.cancel }));
    await waitFor(() => expect(recoveryRequests.cancel).toHaveBeenCalledWith(R1));
  });

  it('needs a fresh second factor before the form', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    render();
    await userEvent.click(await screen.findByRole('button', { name: r.new.action }));
    expect(await screen.findByText(r.stepUpBody)).toBeInTheDocument();
  });

  it('signs and files exactly the ticked conversations with every key of each', async () => {
    const { recoveryRequests, recoveryCrypto } = render();
    await userEvent.click(await screen.findByRole('button', { name: r.new.action }));
    await userEvent.selectOptions(await screen.findByLabelText(r.new.employee), 'alice');
    const list = (await screen.findAllByRole('checkbox'))[0].closest('ul') as HTMLElement;
    const boxes = within(list).getAllByRole('checkbox');
    await userEvent.click(boxes[1]);
    const submit = screen.getByRole('button', { name: r.new.submit });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText(r.new.reason), 'Employee left.');
    await userEvent.click(submit);

    await waitFor(() => expect(recoveryRequests.file).toHaveBeenCalled());
    const [signed] = vi.mocked(recoveryCrypto.signRequest).mock.calls[0];
    expect(signed.scope).toEqual([
      { conversationId: C2, keyId: 'k2' },
      { conversationId: C2, keyId: 'k3' },
    ]);
    const [filed] = vi.mocked(recoveryRequests.file).mock.calls[0];
    expect(filed.conversationIds).toEqual([C2]);
  });
});
