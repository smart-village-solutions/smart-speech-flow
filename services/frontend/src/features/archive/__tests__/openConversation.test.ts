import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ArchiveCrypto, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { type Bytes, fromBuffer, toHex, utf8 } from '@/core/crypto/bytes';
import type { CeremonyCrypto } from '@/core/crypto/ceremony-crypto.port';
import { AppError } from '@/core/http/AppError';
import {
  type ArchiveRepository,
  ConversationNotOpenError,
  ObjectNotStoredError,
} from '@/domain/archive/archive.repository';
import type { OpenedConversation } from '@/domain/archive/archive.types';
import { openConversation } from '@/features/archive/openConversation';
import { verifyConversation } from '@/features/archive/verifyConversation';
import { IDS, consentJson, messageJson } from './archiveFixture';

vi.mock('@/features/archive/verifyConversation', () => ({ verifyConversation: vi.fn() }));

const identity = { tenantId: 'tenant-kassel', userSub: 'alice' };
const KEY = { type: 'secret' } as CryptoKey;
const envelope = (entryId: string) => utf8(`envelope-of-${entryId}`);
// Every entry decrypts to a valid record, so only the hash check can mark one damaged.
const plaintexts = new Map<string, unknown>([
  [IDS.consent, consentJson()],
  [IDS.message, messageJson()],
  [IDS.failed, messageJson({ error: { stage: 'asr', code: 'X', message: null } })],
]);

async function hex(data: Bytes) {
  return toHex(fromBuffer(await crypto.subtle.digest('SHA-256', data)));
}

/** Entries whose signed listings name the envelopes the fake store serves. */
async function conversation(): Promise<OpenedConversation> {
  const entry = async (
    seq: number,
    entryId: string,
    kind: string,
    type: string,
    keyId = IDS.key
  ) => ({
    seq,
    entryId,
    kind,
    windowId: IDS.window,
    keyId,
    objects: JSON.stringify([
      {
        key: `${IDS.conversation}/${entryId}/${type}`,
        sha256: await hex(envelope(entryId)),
        size: envelope(entryId).length,
        type,
      },
    ]),
    prevHash: new Uint8Array(32),
    hash: new Uint8Array(32),
    signerKeyId: 'gk-1',
    signature: new Uint8Array(64),
    createdAt: `2026-10-29T10:0${seq}:00+00:00`,
    storedTypes: [type],
  });
  return {
    conversation: {
      conversationId: IDS.conversation,
      employeeSub: 'alice',
      legalBasis: 'consent',
      startedAt: 's',
      endedAt: 'e',
      retentionUntil: 'r',
      legalHold: false,
      incomplete: false,
      verification: 'not_verified',
    },
    windows: [],
    entries: [
      await entry(1, IDS.consent, 'consent', 'consent.json'),
      await entry(2, IDS.message, 'message', 'record.json'),
      await entry(3, IDS.unstored, 'message', 'record.json'),
      await entry(4, IDS.failed, 'failed', 'record.json'),
      await entry(5, IDS.otherKey, 'message', 'record.json', IDS.unwrappedKey),
    ],
    stamps: [],
    keys: [],
  };
}

function deps(opened: OpenedConversation) {
  const archive = {
    open: vi.fn().mockResolvedValue(opened),
    trust: vi.fn().mockResolvedValue({}),
    object: vi.fn((_c: string, entryId: string) => {
      if (entryId === IDS.unstored) return Promise.reject(new ObjectNotStoredError());
      if (entryId === IDS.failed) return Promise.resolve(utf8('someone else’s bytes'));
      return Promise.resolve(envelope(entryId));
    }),
    reportIntegrity: vi.fn().mockResolvedValue(undefined),
  } as unknown as ArchiveRepository;
  const archiveCrypto = {
    openObject: vi.fn((_key: CryptoKey, address: { entryId: string }) =>
      Promise.resolve(utf8(JSON.stringify(plaintexts.get(address.entryId))))
    ),
  } as unknown as ArchiveCrypto;
  return { archive, archiveCrypto, ceremonyCrypto: {} as CeremonyCrypto, identity };
}

describe('openConversation', () => {
  beforeEach(() => vi.mocked(verifyConversation).mockReset());

  it('reports a failed check and fetches no object', async () => {
    vi.mocked(verifyConversation).mockResolvedValue({ ok: false, stage: 'chain' });
    const d = deps(await conversation());
    expect(await openConversation(d, IDS.conversation, {} as UnlockedKeys)).toEqual({
      status: 'broken',
      stage: 'chain',
    });
    expect(d.archive.reportIntegrity).toHaveBeenCalledWith(IDS.conversation, 'chain');
    expect(d.archive.object).not.toHaveBeenCalled();
  });

  it('decrypts what matches its signed listing, and marks the rest', async () => {
    vi.mocked(verifyConversation).mockResolvedValue({
      ok: true,
      keys: new Map([[IDS.key, KEY]]),
      stamps: [],
    });
    const d = deps(await conversation());
    const result = await openConversation(d, IDS.conversation, {} as UnlockedKeys);
    if (result.status !== 'ready') throw new Error(result.status);
    expect(result.view.entries.map((e) => [e.entry.entryId, e.state])).toEqual([
      [IDS.consent, 'ok'],
      [IDS.message, 'ok'],
      [IDS.unstored, 'notStored'],
      [IDS.failed, 'damaged'],
      [IDS.otherKey, 'noKey'],
    ]);
    expect(vi.mocked(d.archive.object).mock.calls.map((call) => call[1])).not.toContain(
      IDS.otherKey
    );
    expect(vi.mocked(d.archiveCrypto.openObject).mock.calls[0][1]).toEqual({
      tenantId: 'tenant-kassel',
      conversationId: IDS.conversation,
      entryId: IDS.consent,
      objectType: 'consent.json',
      keyId: IDS.key,
    });
    expect(result.view.header.guestName).toBe('Amira Haddad');
    expect(d.archive.reportIntegrity).toHaveBeenCalledWith(IDS.conversation, 'object');
  });

  it('refuses a conversation other than the one asked for, or not the caller’s', async () => {
    vi.mocked(verifyConversation).mockResolvedValue({
      ok: true,
      keys: new Map([[IDS.key, KEY]]),
      stamps: [],
    });
    const swapped = await conversation();
    swapped.conversation.conversationId = IDS.window;
    expect(await openConversation(deps(swapped), IDS.conversation, {} as UnlockedKeys)).toEqual({
      status: 'broken',
      stage: 'chain',
    });
    const someoneElses = await conversation();
    someoneElses.conversation.employeeSub = 'bob';
    expect(
      await openConversation(deps(someoneElses), IDS.conversation, {} as UnlockedKeys)
    ).toEqual({
      status: 'broken',
      stage: 'chain',
    });
    expect(verifyConversation).not.toHaveBeenCalled();
  });

  it('opens the conversation again when the hour since its open has passed, then fetches', async () => {
    vi.mocked(verifyConversation).mockResolvedValue({
      ok: true,
      keys: new Map([[IDS.key, KEY]]),
      stamps: [],
    });
    const d = deps(await conversation());
    const served = d.archive.object;
    let expired = true;
    d.archive.object = vi.fn((...args: Parameters<ArchiveRepository['object']>) => {
      if (args[1] === IDS.consent && expired) {
        expired = false;
        return Promise.reject(new ConversationNotOpenError());
      }
      return served(...args);
    });
    const result = await openConversation(d, IDS.conversation, {} as UnlockedKeys);
    if (result.status !== 'ready') throw new Error(result.status);
    expect(result.view.entries[0].state).toBe('ok');
    expect(d.archive.open).toHaveBeenCalledTimes(2);
  });

  it('fails the open on a transient fetch error instead of calling an entry damaged', async () => {
    vi.mocked(verifyConversation).mockResolvedValue({
      ok: true,
      keys: new Map([[IDS.key, KEY]]),
      stamps: [],
    });
    const d = deps(await conversation());
    d.archive.object = vi.fn().mockRejectedValue(new AppError('server', { status: 503 }));
    await expect(openConversation(d, IDS.conversation, {} as UnlockedKeys)).rejects.toBeInstanceOf(
      AppError
    );
    expect(d.archive.reportIntegrity).not.toHaveBeenCalled();
  });

  it('fetches a few objects at a time, not all at once', async () => {
    vi.mocked(verifyConversation).mockResolvedValue({
      ok: true,
      keys: new Map([[IDS.key, KEY]]),
      stamps: [],
    });
    const d = deps(await conversation());
    const served = d.archive.object;
    let inFlight = 0;
    let most = 0;
    d.archive.object = vi.fn(async (...args: Parameters<ArchiveRepository['object']>) => {
      inFlight += 1;
      most = Math.max(most, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 1));
      inFlight -= 1;
      return served(...args);
    });
    await openConversation(d, IDS.conversation, {} as UnlockedKeys);
    expect(most).toBe(3);
  });
});
