import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity } from '@/app/auth/keycloak';
import type { ArchiveCrypto, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import {
  AmendmentNotStoredError,
  type ArchiveRepository,
  ObjectNotStoredError,
} from '@/domain/archive/archive.repository';
import { ConversationViewer } from '@/features/archive/ConversationViewer';
import { buildTimeline } from '@/features/archive/timeline';
import { type Opened, useObjectOpener, useOpenedConversation } from '@/features/archive/useArchive';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';
import { IDS, loadedFixture, openedConversation } from './archiveFixture';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
}));
vi.mock('@/features/archive/useArchive', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/archive/useArchive')>()),
  useOpenedConversation: vi.fn(),
  useObjectOpener: vi.fn(),
}));

const keys = new Map([[IDS.key, {} as CryptoKey]]);

function ready(): Opened {
  const opened = openedConversation();
  return {
    status: 'ready',
    opened,
    keys,
    stamps: [{ headSeq: 9, genTime: '2026-10-29T10:20:05.000Z' }],
    view: buildTimeline(opened, loadedFixture(), keys),
  };
}

function render(
  state: Opened = ready(),
  openObject = vi.fn().mockResolvedValue(new Uint8Array([82, 73, 70, 70]))
) {
  vi.mocked(useOpenedConversation).mockReturnValue(state);
  vi.mocked(useObjectOpener).mockReturnValue(openObject);
  const view = renderWithProviders(
    <ConversationViewer conversationId={IDS.conversation} unlocked={{} as UnlockedKeys} />,
    {
      locale: 'de',
    }
  );
  return { ...view, openObject };
}

const archive = de.admin.archive;

describe('ConversationViewer', () => {
  beforeEach(() => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:audio-1');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
  });
  afterEach(() => vi.restoreAllMocks());

  it('shows nothing but the check while it runs, and only the error when it fails', () => {
    render({ status: 'checking' });
    expect(screen.getByText(archive.checking)).toBeInTheDocument();
    render({ status: 'broken', stage: 'wrap' });
    expect(screen.getByRole('alert')).toHaveTextContent(archive.integrity.wrap);
    expect(screen.queryByText('Amira Haddad')).not.toBeInTheDocument();
  });

  it('heads the conversation with guest, basis, retention and an unverified stamp', () => {
    render();
    const header = within(screen.getByRole('heading', { level: 1 }).parentElement as HTMLElement);
    expect(header.getByText(/Amira Haddad/)).toBeInTheDocument();
    expect(header.getByText(archive.basis.consent)).toBeInTheDocument();
    expect(header.getByText(archive.incomplete)).toBeInTheDocument();
    expect(screen.getByText(/Aufbewahrt bis 29\.10\.2027/)).toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(archive.stamp.unverified.replace(/[()]/g, String.raw`\$&`)))
    ).toBeInTheDocument();
  });

  it('lists every gap with its time', () => {
    render();
    const gaps = within(
      screen.getByRole('heading', { name: archive.gaps.title }).closest('section') as HTMLElement
    );
    expect(gaps.getByText(/Pausiert: Verbindung unterbrochen/)).toBeInTheDocument();
    expect(gaps.getByText(archive.gaps.failed)).toBeInTheDocument();
    expect(gaps.getByText(archive.gaps.notStored)).toBeInTheDocument();
    expect(gaps.getByText(archive.gaps.noKey)).toBeInTheDocument();
  });

  it('puts amendments beside the message, marked superseded and by another author', () => {
    render();
    const message = screen.getByText('مرحبا').closest('li') as HTMLElement;
    expect(within(message).getByText('Name korrigiert')).toBeInTheDocument();
    expect(within(message).getByText('Korrektur')).toBeInTheDocument();
    expect(within(message).getByText(/\(ersetzt\)/)).toBeInTheDocument();
    expect(within(message).getByText(/\(anderer Verfasser\)/)).toBeInTheDocument();
    expect(screen.getByText(archive.amendment.unattached)).toBeInTheDocument();
  });

  it('shows a damaged entry as damaged, without its content', () => {
    const opened = openedConversation();
    const loaded = loadedFixture();
    loaded.set(IDS.message, 'damaged');
    render({ ...ready(), view: buildTimeline(opened, loaded, keys) } as Opened);
    expect(screen.getByText(archive.entry.damaged)).toBeInTheDocument();
    expect(screen.queryByText('مرحبا')).not.toBeInTheDocument();
  });

  it('plays audio from a Blob URL it revokes when the viewer closes', async () => {
    const { openObject, unmount } = render();
    const [original] = screen.getAllByRole('button', { name: archive.audio.original });
    await userEvent.click(original);
    expect(openObject).toHaveBeenCalledWith(expect.anything(), keys, IDS.message, 'original.wav');
    expect(await screen.findByLabelText(archive.audio.original)).toHaveAttribute(
      'src',
      'blob:audio-1'
    );
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audio-1');
  });

  it('creates no Blob URL for audio that finishes decrypting after the viewer closed', async () => {
    let finish: (bytes: Uint8Array) => void = () => undefined;
    const pending = new Promise<Uint8Array>((resolve) => {
      finish = resolve;
    });
    const { unmount } = render(ready(), vi.fn().mockReturnValue(pending));
    const [original] = screen.getAllByRole('button', { name: archive.audio.original });
    await userEvent.click(original);
    unmount();
    finish(new Uint8Array([1]));
    await pending;
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('says audio the store has not confirmed yet is not stored, not damaged', async () => {
    render(ready(), vi.fn().mockRejectedValue(new ObjectNotStoredError()));
    const message = screen.getByText('مرحبا').closest('li') as HTMLElement;
    const [original] = within(message).getAllByRole('button', { name: archive.audio.original });
    await userEvent.click(original);
    expect(await within(message).findByText(archive.entry.notStored)).toBeInTheDocument();
    expect(within(message).queryByText(archive.entry.damaged)).not.toBeInTheDocument();
  });

  it('keeps an unconfirmed amendment after its dialog closed, and blocks new ones until it is sent', async () => {
    const amend = vi
      .fn()
      .mockRejectedValueOnce(new AmendmentNotStoredError())
      .mockResolvedValueOnce({ entryId: 'x', seq: 10 });
    const archiveCrypto = {
      sealObject: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
    } as unknown as ArchiveCrypto;
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    vi.mocked(useOpenedConversation).mockReturnValue(ready());
    vi.mocked(useObjectOpener).mockReturnValue(vi.fn());
    renderWithProviders(
      <ConversationViewer conversationId={IDS.conversation} unlocked={{} as UnlockedKeys} />,
      {
        locale: 'de',
        services: { archive: { amend } as unknown as ArchiveRepository, archiveCrypto },
      }
    );
    const message = screen.getByText('مرحبا').closest('li') as HTMLElement;
    const amendButtons = within(message).getAllByRole('button', { name: archive.amend });
    await userEvent.click(amendButtons[amendButtons.length - 1]);
    await userEvent.type(screen.getByLabelText(archive.amendment.text), 'Korrektur');
    await userEvent.click(screen.getByRole('button', { name: archive.amendment.submit }));
    await screen.findByText(archive.amendment.error.notStored);
    await userEvent.click(screen.getByRole('button', { name: archive.amendment.cancel }));

    expect(await screen.findByText(archive.amendment.pending)).toBeInTheDocument();
    expect(screen.queryAllByRole('button', { name: archive.amend })).toEqual([]);
    await userEvent.click(screen.getByRole('button', { name: archive.amendment.retry }));
    await waitFor(() => expect(amend).toHaveBeenCalledTimes(2));
    expect(amend.mock.calls[1]).toEqual(amend.mock.calls[0]);
  });

  it("offers no amendment on someone else's conversation (§10.4)", () => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'sam' });
    render();
    expect(screen.queryAllByRole('button', { name: archive.amend })).toEqual([]);
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    render();
    expect(screen.getAllByRole('button', { name: archive.amend }).length).toBeGreaterThan(0);
  });
});
