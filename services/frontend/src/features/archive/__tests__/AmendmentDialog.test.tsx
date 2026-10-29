import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity } from '@/app/auth/keycloak';
import type { ArchiveCrypto } from '@/core/crypto/archive-crypto.port';
import {
  AmendmentNotStoredError,
  type ArchiveRepository,
} from '@/domain/archive/archive.repository';
import type { OpenedConversation } from '@/domain/archive/archive.types';
import { AmendmentDialog } from '@/features/archive/AmendmentDialog';
import { useAmend } from '@/features/archive/useAmend';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';
import { IDS, openedConversation } from './archiveFixture';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
}));

const text = de.admin.archive.amendment;
const NEWER = '0b1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4f';

/** Two keys the caller holds; the newer one has no recovery wrap. */
function conversation(): OpenedConversation {
  const opened = openedConversation();
  opened.keys = [
    { keyId: IDS.key, epoch: 1, recoveryWrapped: true, wrap: null },
    { keyId: NEWER, epoch: 2, recoveryWrapped: false, wrap: null },
  ];
  return opened;
}

const opened = conversation();
const keys = new Map([
  [IDS.key, { type: 'secret' } as CryptoKey],
  [NEWER, { type: 'secret' } as CryptoKey],
]);

/** The dialog as the viewer drives it: the amend state belongs to the viewer. */
function Harness({ onAdded }: Readonly<{ onAdded: () => void }>) {
  const amend = useAmend(opened, keys, onAdded);
  return (
    <AmendmentDialog opened={opened} amend={amend} references={[IDS.message]} onClose={vi.fn()} />
  );
}

function render(
  amend: ArchiveRepository['amend'] = vi.fn().mockResolvedValue({ entryId: 'x', seq: 10 })
) {
  const archive = { amend } as unknown as ArchiveRepository;
  const archiveCrypto = {
    sealObject: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
  } as unknown as ArchiveCrypto;
  const onAdded = vi.fn();
  renderWithProviders(<Harness onAdded={onAdded} />, {
    locale: 'de',
    services: { archive, archiveCrypto },
  });
  return { archive, archiveCrypto, onAdded };
}

async function write(value: string) {
  await userEvent.type(screen.getByLabelText(text.text), value);
  await userEvent.click(screen.getByRole('button', { name: text.submit }));
}

describe('AmendmentDialog', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
  });

  it('seals under the newest key recovery can open too, and posts it', async () => {
    const { archive, archiveCrypto, onAdded } = render();
    await write('Name korrigiert');
    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    const [, address, plaintext] = vi.mocked(archiveCrypto.sealObject).mock.calls[0];
    expect(address).toMatchObject({
      keyId: IDS.key,
      objectType: 'amendment.json',
      conversationId: IDS.conversation,
      tenantId: 'tenant-kassel',
    });
    expect(JSON.parse(new TextDecoder().decode(plaintext))).toMatchObject({
      references: [IDS.message],
      text: 'Name korrigiert',
      author_sub: 'alice',
    });
    expect(archive.amend).toHaveBeenCalledWith(IDS.conversation, {
      entryId: address.entryId,
      keyId: IDS.key,
      ciphertext: new Uint8Array([1, 2, 3]),
    });
  });

  it.each([
    ['a failed store write', new AmendmentNotStoredError(), text.error.notStored],
    [
      'any other failure, since the gateway may hold the entry already',
      new Error('timeout'),
      text.error.failed,
    ],
  ])('re-posts the same entry and bytes after %s', async (_case, error, message) => {
    const amend = vi
      .fn()
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce({ entryId: 'x', seq: 10 });
    const { archive, archiveCrypto, onAdded } = render(amend);
    await write('Korrektur');
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    await userEvent.click(screen.getByRole('button', { name: text.retry }));
    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    const [first, second] = vi.mocked(archive.amend).mock.calls;
    expect(second).toEqual(first);
    expect(archiveCrypto.sealObject).toHaveBeenCalledTimes(1);
  });

  it('posts nothing while the text is empty', async () => {
    const { archive } = render();
    await userEvent.type(screen.getByLabelText(text.text), '   ');
    expect(screen.getByRole('button', { name: text.submit })).toBeDisabled();
    expect(archive.amend).not.toHaveBeenCalled();
  });
});
