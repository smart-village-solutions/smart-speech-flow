import type { ArchiveCrypto, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { type Bytes, fromBuffer, toHex } from '@/core/crypto/bytes';
import type { CeremonyCrypto } from '@/core/crypto/ceremony-crypto.port';
import { listedObjects } from '@/core/crypto/chain';
import { AppError } from '@/core/http/AppError';
import {
  type ArchiveRepository,
  ConversationNotOpenError,
  type IntegrityStage,
  ObjectNotStoredError,
} from '@/domain/archive/archive.repository';
import type { OpenedConversation } from '@/domain/archive/archive.types';
import { JSON_OBJECT, parseRecord } from './records';
import { type Loaded, type Timeline, buildTimeline } from './timeline';
import { type StampView, verifyConversation } from './verifyConversation';

export type Opened =
  | { status: 'checking' }
  | { status: 'unavailable' }
  | { status: 'broken'; stage: string }
  | {
      status: 'ready';
      opened: OpenedConversation;
      keys: Map<string, CryptoKey>;
      stamps: StampView[];
      view: Timeline;
    };

export interface OpenDeps {
  archive: ArchiveRepository;
  archiveCrypto: ArchiveCrypto;
  ceremonyCrypto: CeremonyCrypto;
  identity: { tenantId: string; userSub: string };
}

async function sha256Hex(data: Bytes): Promise<string> {
  return toHex(fromBuffer(await crypto.subtle.digest('SHA-256', data)));
}

/** After the gateway's hour, one audited open again and one more try (§10.6). */
async function fetchObject(
  deps: Readonly<OpenDeps>,
  conversationId: string,
  entryId: string,
  objectType: string
): Promise<Bytes> {
  try {
    return await deps.archive.object(conversationId, entryId, objectType);
  } catch (error) {
    if (!(error instanceof ConversationNotOpenError)) throw error;
    await deps.archive.open(conversationId);
    return deps.archive.object(conversationId, entryId, objectType);
  }
}

/** Ciphertext exactly as the signed entry lists it (§10.6 step 5), then opened under A.3. */
export async function openObject(
  deps: Readonly<OpenDeps>,
  opened: OpenedConversation,
  keys: ReadonlyMap<string, CryptoKey>,
  entryId: string,
  objectType: string
): Promise<Bytes> {
  const entry = opened.entries.find((candidate) => candidate.entryId === entryId);
  const key = entry === undefined ? undefined : keys.get(entry.keyId);
  const listed =
    entry === undefined ? undefined : listedObjects(entry).find((o) => o.type === objectType);
  if (entry === undefined || key === undefined || listed === undefined)
    throw new Error('not openable');
  const conversationId = opened.conversation.conversationId;
  const envelope = await fetchObject(deps, conversationId, entryId, objectType);
  if (envelope.length !== listed.size || (await sha256Hex(envelope)) !== listed.sha256) {
    throw new Error('ciphertext differs from the signed entry');
  }
  const address = {
    tenantId: deps.identity.tenantId,
    conversationId,
    entryId,
    objectType,
    keyId: entry.keyId,
  };
  return deps.archiveCrypto.openObject(key, address, envelope);
}

/** A few at a time: each fetch holds one of the gateway's pooled database connections. */
const LOAD_BATCH = 3;

async function inBatches<T, R>(items: readonly T[], work: (item: T) => Promise<R>): Promise<R[]> {
  if (items.length === 0) return [];
  const head = await Promise.all(items.slice(0, LOAD_BATCH).map(work));
  return [...head, ...(await inBatches(items.slice(LOAD_BATCH), work))];
}

/** Damage is what the bytes prove; a fetch that merely failed fails the open instead. */
function loadedAfter(error: unknown): Loaded {
  if (error instanceof ObjectNotStoredError) return 'notStored';
  if (error instanceof ConversationNotOpenError || (error instanceof AppError && error.retryable)) {
    throw error;
  }
  return 'damaged';
}

async function loadRecords(
  deps: Readonly<OpenDeps>,
  opened: OpenedConversation,
  keys: ReadonlyMap<string, CryptoKey>
): Promise<Map<string, Loaded>> {
  const readable = opened.entries.filter((entry) => keys.has(entry.keyId));
  const records = await inBatches(readable, async (entry): Promise<[string, Loaded]> => {
    try {
      const data = await openObject(
        deps,
        opened,
        keys,
        entry.entryId,
        JSON_OBJECT[entry.kind] ?? ''
      );
      return [entry.entryId, parseRecord(entry.kind, data)];
    } catch (error) {
      return [entry.entryId, loadedAfter(error)];
    }
  });
  return new Map(records);
}

/** A signal for operators; the browser shows the failure whatever the answer. */
function report(deps: Readonly<OpenDeps>, conversationId: string, stage: IntegrityStage): void {
  deps.archive.reportIntegrity(conversationId, stage).catch(() => undefined);
}

function broken(deps: Readonly<OpenDeps>, conversationId: string, stage: IntegrityStage): Opened {
  report(deps, conversationId, stage);
  return { status: 'broken', stage };
}

/** Open, verify, then decrypt (§10.6); a failed check is reported and shows nothing. */
export async function openConversation(
  deps: Readonly<OpenDeps>,
  conversationId: string,
  unlocked: UnlockedKeys
): Promise<Opened> {
  const [opened, trust] = await Promise.all([
    deps.archive.open(conversationId),
    deps.archive.trust(deps.identity.tenantId),
  ]);
  // The opening rule makes it the caller's; anything else was not what was asked for.
  const facts = opened.conversation;
  if (facts.conversationId !== conversationId || facts.employeeSub !== deps.identity.userSub) {
    return broken(deps, conversationId, 'chain');
  }
  const verified = await verifyConversation({ ...deps, ...deps.identity, opened, trust, unlocked });
  if (!verified.ok) return broken(deps, conversationId, verified.stage);
  const loaded = await loadRecords(deps, opened, verified.keys);
  if ([...loaded.values()].includes('damaged')) report(deps, conversationId, 'object');
  return {
    status: 'ready',
    opened,
    keys: verified.keys,
    stamps: verified.stamps,
    view: buildTimeline(opened, loaded, verified.keys),
  };
}
