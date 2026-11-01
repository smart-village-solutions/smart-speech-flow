import type { ArchiveCrypto, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { type Bytes, equalBytes } from '@/core/crypto/bytes';
import type { CeremonyCrypto } from '@/core/crypto/ceremony-crypto.port';
import { verifyChain } from '@/core/crypto/chain';
import { readTimestamp } from '@/core/crypto/tst-info';
import type { IntegrityStage } from '@/domain/archive/archive.repository';
import type { ArchiveTrust, OpenedConversation, StampFacts } from '@/domain/archive/archive.types';

export interface StampView {
  headSeq: number;
  /** The authority's time; its CMS signature is checked from #619 on. */
  genTime: string;
}

export type Verified =
  | { ok: true; keys: Map<string, CryptoKey>; stamps: StampView[] }
  | { ok: false; stage: IntegrityStage };

export interface VerifyInput {
  tenantId: string;
  userSub: string;
  opened: OpenedConversation;
  trust: ArchiveTrust;
  unlocked: UnlockedKeys;
  archiveCrypto: ArchiveCrypto;
  ceremonyCrypto: CeremonyCrypto;
}

async function certified(input: Readonly<VerifyInput>): Promise<Map<string, Bytes> | null> {
  try {
    return (await input.ceremonyCrypto.certifyChain(input.trust)).gatewayKeys;
  } catch {
    return null;
  }
}

async function openKeys(
  input: Readonly<VerifyInput>,
  signers: ReadonlyMap<string, Bytes>
): Promise<Map<string, CryptoKey> | null> {
  const keys = new Map<string, CryptoKey>();
  for (const key of input.opened.keys) {
    if (key.wrap === null) continue;
    const wrap = {
      tenantId: input.tenantId,
      conversationId: input.opened.conversation.conversationId,
      keyId: key.keyId,
      recipientRef: input.userSub,
      ...key.wrap,
    };
    try {
      keys.set(key.keyId, await input.archiveCrypto.openWrap(wrap, input.unlocked, signers));
    } catch {
      return null;
    }
  }
  return keys;
}

function stampView(
  opened: Readonly<OpenedConversation>,
  stamp: Readonly<StampFacts>,
  token: Bytes
): StampView | null {
  const head = opened.entries.find((entry) => entry.seq === stamp.headSeq);
  if (head === undefined || !equalBytes(stamp.headHash, head.hash)) return null;
  try {
    const read = readTimestamp(token);
    return equalBytes(read.imprint, head.hash)
      ? { headSeq: stamp.headSeq, genTime: read.genTime }
      : null;
  } catch {
    return null;
  }
}

/** A head without a token yet is pending, not a failure. */
function stampViews(opened: Readonly<OpenedConversation>): StampView[] | null {
  const views: StampView[] = [];
  for (const stamp of opened.stamps) {
    if (stamp.token === null) continue;
    const view = stampView(opened, stamp, stamp.token);
    if (view === null) return null;
    views.push(view);
  }
  return views;
}

/** Spec §10.6 steps 1–4, in order; no key is handed out unless all hold. */
export async function verifyConversation(input: Readonly<VerifyInput>): Promise<Verified> {
  const signers = await certified(input);
  if (signers === null) return { ok: false, stage: 'trust' };
  const keys = await openKeys(input, signers);
  if (keys === null) return { ok: false, stage: 'wrap' };
  const conversationId = input.opened.conversation.conversationId;
  if (!(await verifyChain(input.tenantId, conversationId, input.opened.entries, signers))) {
    return { ok: false, stage: 'chain' };
  }
  const stamps = stampViews(input.opened);
  if (stamps === null) return { ok: false, stage: 'stamp' };
  return { ok: true, keys, stamps };
}
