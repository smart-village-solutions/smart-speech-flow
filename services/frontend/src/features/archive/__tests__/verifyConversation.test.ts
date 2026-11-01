import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import type { ArchiveCrypto, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { fromBase64Url } from '@/core/crypto/bytes';
import { CeremonyCheckError, type CeremonyCrypto } from '@/core/crypto/ceremony-crypto.port';
import type { ArchiveTrust, OpenedConversation } from '@/domain/archive/archive.types';
import { verifyConversation } from '@/features/archive/verifyConversation';

// A chain and a stamp the gateway signed (tests/recording_crypto_vectors.py).
const vectors = JSON.parse(
  readFileSync(
    path.join(
      import.meta.dirname,
      '../../../../../../tests/fixtures/recording/crypto_vectors_v1.json'
    ),
    'utf8'
  )
);
const chain = vectors.chain;
const token = fromBase64Url(vectors.timestamp.der);
const KEY = chain.entries[0].key_id as string;

function opened(overrides: Partial<OpenedConversation> = {}): OpenedConversation {
  const entries = chain.entries.map((e: Record<string, never>) => ({
    seq: e.seq,
    entryId: e.entry_id,
    kind: e.kind,
    windowId: e.window_id,
    keyId: e.key_id,
    objects: e.objects,
    prevHash: fromBase64Url(e.prev_hash),
    hash: fromBase64Url(e.hash),
    signerKeyId: e.signer_key_id,
    signature: fromBase64Url(e.signature),
    createdAt: '2026-10-29T00:00:00+00:00',
    storedTypes: [],
  }));
  return {
    conversation: {
      conversationId: chain.conversation_id,
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
    entries,
    stamps: [{ headSeq: 3, headHash: entries[2].hash, token }],
    keys: [
      {
        keyId: KEY,
        epoch: 1,
        recoveryWrapped: true,
        wrap: { blob: '{}', creatorRef: chain.signer_key_id, creatorSignature: new Uint8Array(64) },
      },
    ],
    ...overrides,
  };
}

const trust = {
  recoveryKeyId: 'rk',
  transcriptHash: new Uint8Array(32),
  facts: {},
  signatures: new Map(),
} as unknown as ArchiveTrust;
const signers = new Map([[chain.signer_key_id as string, fromBase64Url(chain.signer)]]);

function input(
  setup: {
    certifyChain?: CeremonyCrypto['certifyChain'];
    openWrap?: ArchiveCrypto['openWrap'];
    opened?: OpenedConversation;
  } = {}
) {
  const ceremonyCrypto = {
    certifyChain: setup.certifyChain ?? vi.fn().mockResolvedValue({ gatewayKeys: signers }),
  } as unknown as CeremonyCrypto;
  const openWrap = setup.openWrap ?? vi.fn().mockResolvedValue({ type: 'secret' } as CryptoKey);
  const archiveCrypto = { openWrap } as unknown as ArchiveCrypto;
  return {
    tenantId: chain.tenant_id,
    userSub: 'alice',
    opened: setup.opened ?? opened(),
    trust,
    unlocked: {} as UnlockedKeys,
    archiveCrypto,
    ceremonyCrypto,
    openWrap,
  };
}

/** The vector token, with its imprint replaced. */
function tokenNaming(digest: Uint8Array): Uint8Array<ArrayBuffer> {
  const imprint = fromBase64Url(vectors.timestamp.imprint);
  const at = token.findIndex((_, i) => imprint.every((byte, j) => token[i + j] === byte));
  const other = token.slice();
  other.set(digest, at);
  return other;
}

describe('verifyConversation', () => {
  it('certifies the signers, opens the caller’s wraps, checks the chain and reads the stamp', async () => {
    const setup = input();
    const result = await verifyConversation(setup);
    expect(result).toEqual({
      ok: true,
      keys: new Map([[KEY, { type: 'secret' }]]),
      stamps: [{ headSeq: 3, genTime: vectors.timestamp.gen_time }],
    });
    expect(setup.openWrap).toHaveBeenCalledWith(
      expect.objectContaining({
        keyId: KEY,
        recipientRef: 'alice',
        conversationId: chain.conversation_id,
      }),
      setup.unlocked,
      signers
    );
  });

  it('stops at an uncertified ceremony before any wrap is opened', async () => {
    const setup = input({
      certifyChain: () => Promise.reject(new CeremonyCheckError('signature_invalid')),
    });
    expect(await verifyConversation(setup)).toEqual({ ok: false, stage: 'trust' });
    expect(setup.openWrap).not.toHaveBeenCalled();
  });

  it('stops at a wrap that does not open', async () => {
    const setup = input({ openWrap: () => Promise.reject(new Error('refused')) });
    expect(await verifyConversation(setup)).toEqual({ ok: false, stage: 'wrap' });
  });

  it('stops at a tampered chain', async () => {
    const tampered = opened();
    tampered.entries[1] = { ...tampered.entries[1], kind: 'failed' };
    expect(await verifyConversation(input({ opened: tampered }))).toEqual({
      ok: false,
      stage: 'chain',
    });
  });

  it('stops at a stamp naming another head, or stored against another hash', async () => {
    const base = opened();
    const otherImprint = opened({
      stamps: [{ ...base.stamps[0], token: tokenNaming(new Uint8Array(32).fill(9)) }],
    });
    expect(await verifyConversation(input({ opened: otherImprint }))).toEqual({
      ok: false,
      stage: 'stamp',
    });
    const otherHead = opened({ stamps: [{ ...base.stamps[0], headSeq: 2 }] });
    expect(await verifyConversation(input({ opened: otherHead }))).toEqual({
      ok: false,
      stage: 'stamp',
    });
    const garbage = opened({
      stamps: [{ ...base.stamps[0], token: new Uint8Array([0x30, 0x00]) }],
    });
    expect(await verifyConversation(input({ opened: garbage }))).toEqual({
      ok: false,
      stage: 'stamp',
    });
  });

  it('takes an unstamped head as pending, and a key without a wrap as nothing to open', async () => {
    const pending = opened({ stamps: [{ headSeq: 3, headHash: new Uint8Array(32), token: null }] });
    pending.keys.push({ keyId: 'k2', epoch: 2, recoveryWrapped: true, wrap: null });
    const setup = input({ opened: pending });
    const result = await verifyConversation(setup);
    expect(result).toMatchObject({ ok: true, stamps: [] });
    expect(setup.openWrap).toHaveBeenCalledTimes(1);
  });
});
