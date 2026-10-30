import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { createKeyVault } from '@/core/crypto/key-vault';
import type { ArchiveRepository } from '@/domain/archive/archive.repository';
import type { OwnConversation } from '@/domain/archive/archive.types';
import { ArchiveScreen } from '@/features/archive/ArchiveScreen';
import { verifyConversation } from '@/features/archive/verifyConversation';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';
import { openedConversation } from './archiveFixture';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
}));
vi.mock('@/features/archive/verifyConversation', () => ({ verifyConversation: vi.fn() }));

const keys = { fingerprint: new Uint8Array(32) } as unknown as UnlockedKeys;

function row(overrides: Partial<OwnConversation> = {}): OwnConversation {
  return {
    conversationId: '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f',
    employeeSub: 'alice',
    employeeName: null,
    recovered: false,
    startedAt: '2026-10-29T10:00:00+00:00',
    endedAt: '2026-10-29T10:20:00+00:00',
    retentionUntil: '2027-10-29T10:00:00+00:00',
    legalHold: false,
    incomplete: false,
    messages: 3,
    amendments: 0,
    verification: 'not_verified',
    ...overrides,
  };
}

interface RenderOptions {
  unlocked: UnlockedKeys | null;
  pages?: OwnConversation[][];
  locked?: number;
  onOpenKeyRecovery?: () => void;
}

function render(options: RenderOptions) {
  const keyVault = createKeyVault();
  if (options.unlocked !== null) keyVault.hold(options.unlocked);
  const pages = [...(options.pages ?? [[row()]])];
  const archive = {
    list: vi.fn(() => Promise.resolve(pages.shift() ?? [])),
    open: vi.fn().mockResolvedValue(openedConversation()),
    trust: vi.fn().mockResolvedValue({}),
    object: vi.fn(),
    amend: vi.fn(),
    reportIntegrity: vi.fn().mockResolvedValue(undefined),
  } as unknown as ArchiveRepository;
  const onOpenKeys = vi.fn();
  const locked = options.locked ?? 0;
  const recoveryRequests = {
    ownCandidates: vi.fn().mockResolvedValue({
      conversations: locked > 0 ? [row()] : [],
      remaining: { conversations: Math.max(locked - 1, 0), keys: 0 },
    }),
  };
  renderWithProviders(
    <ArchiveScreen
      onBack={vi.fn()}
      onOpenKeys={onOpenKeys}
      onOpenKeyRecovery={options.onOpenKeyRecovery}
      onSignOut={vi.fn()}
    />,
    {
      locale: 'de',
      services: { archive, keyVault, recoveryRequests } as never,
    }
  );
  return { archive, onOpenKeys, recoveryRequests };
}

// Staff screens render in German (useScreenLocale('de')).
describe('ArchiveScreen', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    vi.mocked(verifyConversation).mockReset();
  });

  it('sends a locked user to unlock their keys first, and lists nothing', async () => {
    const { archive, onOpenKeys } = render({ unlocked: null });
    await userEvent.click(await screen.findByRole('button', { name: de.admin.archive.unlock }));
    expect(onOpenKeys).toHaveBeenCalled();
    expect(archive.list).not.toHaveBeenCalled();
  });

  it('lists clear metadata only, and opens a conversation on a tap', async () => {
    vi.mocked(verifyConversation).mockReturnValue(new Promise(() => undefined));
    const { archive } = render({
      unlocked: keys,
      pages: [[row({ incomplete: true, legalHold: true })]],
    });
    expect(await screen.findByText(de.admin.archive.incomplete)).toBeInTheDocument();
    expect(screen.getByText(de.admin.archive.hold)).toBeInTheDocument();
    expect(screen.getByText(de.admin.archive.verification.not_verified)).toBeInTheDocument();
    expect(screen.queryByText('Amira Haddad')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /29\.10\.2026/ }));
    expect(archive.open).toHaveBeenCalledWith(row().conversationId);
    expect(await screen.findByText(de.admin.archive.checking)).toBeInTheDocument();
  });

  it('pages on with the last row’s start and ID', async () => {
    const full = Array.from({ length: 50 }, (_, i) =>
      row({ conversationId: `6f1c1d2e-3a4b-4c5d-8e9f-${String(i).padStart(12, '0')}` })
    );
    const { archive } = render({ unlocked: keys, pages: [full, [row()]] });
    await userEvent.click(await screen.findByRole('button', { name: de.admin.archive.more }));
    await waitFor(() =>
      expect(archive.list).toHaveBeenLastCalledWith({
        startedBefore: full[49].startedAt,
        beforeId: full[49].conversationId,
      })
    );
  });

  it('shows an integrity error and no content when the chain is broken, and reports it', async () => {
    vi.mocked(verifyConversation).mockResolvedValue({ ok: false, stage: 'chain' });
    const { archive } = render({ unlocked: keys });
    await userEvent.click(await screen.findByRole('button', { name: /29\.10\.2026/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent(de.admin.archive.integrity.chain);
    expect(archive.object).not.toHaveBeenCalled();
    expect(archive.reportIntegrity).toHaveBeenCalledWith(row().conversationId, 'chain');
    expect(screen.queryByText('Amira Haddad')).not.toBeInTheDocument();
  });

  it('tags a recovered conversation with its employee and opens it as theirs', async () => {
    vi.mocked(verifyConversation).mockReturnValue(new Promise(() => undefined));
    const recovered = row({ employeeSub: 'bob', employeeName: 'Bob Employee', recovered: true });
    const { archive } = render({ unlocked: keys, pages: [[recovered]] });
    const served = openedConversation();
    served.conversation.employeeSub = 'bob';
    vi.mocked(archive.open).mockResolvedValue(served);
    await userEvent.click(await screen.findByText('Wiederhergestellt: Bob Employee'));
    await waitFor(() => expect(archive.open).toHaveBeenCalledWith(recovered.conversationId));
    // Checks start only for the employee the list named; bob's would be refused as alice's.
    await waitFor(() => expect(verifyConversation).toHaveBeenCalled());
  });

  it('points to key recovery when the key cannot open some conversations', async () => {
    const onOpenKeyRecovery = vi.fn();
    render({ unlocked: keys, locked: 3, onOpenKeyRecovery });
    const banner = de.admin.keyRecovery.banner.replace('{{count}}', '3');
    expect(await screen.findByText(banner)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: de.admin.keyRecovery.open }));
    expect(onOpenKeyRecovery).toHaveBeenCalledOnce();
  });

  it('shows no banner when the key opens everything', async () => {
    const { recoveryRequests } = render({ unlocked: keys, onOpenKeyRecovery: vi.fn() });
    await waitFor(() => expect(recoveryRequests.ownCandidates).toHaveBeenCalled());
    expect(
      screen.queryByRole('button', { name: de.admin.keyRecovery.open })
    ).not.toBeInTheDocument();
  });
});
