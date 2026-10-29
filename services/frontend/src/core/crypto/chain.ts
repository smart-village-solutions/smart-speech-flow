import { type Bytes, equalBytes } from './bytes';
import type { Field } from './encoding';
import { signedDigest, verifyFields } from './signatures';
import { TAGS } from './tags';

/** One chain entry as the gateway serves it (spec §11.1, A.6). */
export interface SignedEntry {
  seq: number;
  entryId: string;
  kind: string;
  windowId: string | null;
  keyId: string;
  /** The exact text the signature covers. */
  objects: string;
  prevHash: Bytes;
  hash: Bytes;
  signerKeyId: string;
  signature: Bytes;
}

export interface ListedObject {
  type: string;
  key: string;
  size: number;
  sha256: string;
}

const GENESIS = new Uint8Array(32);

export function listedObjects(entry: Readonly<SignedEntry>): ListedObject[] {
  const parsed: unknown = JSON.parse(entry.objects);
  if (!Array.isArray(parsed)) throw new TypeError('objects are not a list');
  return parsed.map((item: Record<string, unknown>) => ({
    type: String(item.type),
    key: String(item.key),
    size: Number(item.size),
    sha256: String(item.sha256),
  }));
}

function fields(tenantId: string, conversationId: string, entry: Readonly<SignedEntry>): Field[] {
  return [
    tenantId,
    conversationId,
    entry.seq,
    entry.kind,
    entry.windowId ?? '',
    entry.keyId,
    entry.objects,
    entry.prevHash,
  ];
}

/** The entry ID is not signed; its signed object keys bind it (spec §10.6). */
function keysNameEntry(conversationId: string, entry: Readonly<SignedEntry>): boolean {
  try {
    const objects = listedObjects(entry);
    return (
      objects.length > 0 &&
      objects.every((o) => o.key === `${conversationId}/${entry.entryId}/${o.type}`)
    );
  } catch {
    return false;
  }
}

async function entryHolds(
  tenantId: string,
  conversationId: string,
  entry: Readonly<SignedEntry>,
  signers: ReadonlyMap<string, Bytes>
): Promise<boolean> {
  const signer = signers.get(entry.signerKeyId);
  if (signer === undefined || !keysNameEntry(conversationId, entry)) return false;
  const signed = fields(tenantId, conversationId, entry);
  if (!equalBytes(await signedDigest(TAGS.chainSig, signed), entry.hash)) return false;
  return verifyFields(signer, entry.signature, TAGS.chainSig, signed);
}

/** Entries in `seq` order from 1, each linked to the last and signed by an accepted key. */
export async function verifyChain(
  tenantId: string,
  conversationId: string,
  entries: readonly SignedEntry[],
  signers: ReadonlyMap<string, Bytes>
): Promise<boolean> {
  let previous: Bytes = GENESIS;
  for (const [index, entry] of entries.entries()) {
    if (entry.seq !== index + 1 || !equalBytes(entry.prevHash, previous)) return false;
    if (!(await entryHolds(tenantId, conversationId, entry, signers))) return false;
    previous = entry.hash;
  }
  return true;
}
