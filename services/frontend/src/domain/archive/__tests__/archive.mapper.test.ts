import { describe, expect, it } from 'vitest';
import { toBase64Url } from '@/core/crypto/bytes';
import { publicPoint } from '@/core/crypto/curve';
import { toOpened, toOwnConversations, toTrust } from '@/domain/archive/archive.mapper';

const b = (n: number, length: number) => toBase64Url(new Uint8Array(length).fill(n));
const ID = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';

const opened = {
  conversation: {
    conversation_id: ID,
    employee_sub: 'alice',
    legal_basis: 'consent',
    started_at: 's',
    ended_at: 'e',
    retention_until: 'r',
    legal_hold: false,
    incomplete: false,
    verification: 'not_verified',
  },
  windows: [
    {
      window_id: ID,
      opened_at: 'o',
      closed_at: null,
      close_reason: null,
      pauses: [{ at: 'p', reason: 'liveness', resumed_at: null }],
    },
  ],
  entries: [
    {
      seq: 1,
      entry_id: ID,
      kind: 'consent',
      window_id: null,
      key_id: ID,
      objects: '[{"a":1}]',
      prev_hash: b(0, 32),
      hash: b(1, 32),
      signer_key_id: 'gk-1',
      signature: b(2, 64),
      created_at: 'c',
      stored_types: ['consent.json'],
    },
  ],
  stamps: [{ head_seq: 1, head_hash: b(1, 32), token: null }],
  keys: [{ key_id: ID, epoch: 1, recovery_wrapped: true, wrap: null }],
};

describe('archive mapper', () => {
  it('maps the list', () => {
    const [row] = toOwnConversations({
      conversations: [
        {
          conversation_id: ID,
          started_at: 's',
          ended_at: 'e',
          retention_until: 'r',
          legal_hold: false,
          incomplete: true,
          messages: 3,
          amendments: 1,
          verification: 'not_verified',
        },
      ],
    });
    expect(row).toMatchObject({
      conversationId: ID,
      incomplete: true,
      messages: 3,
      verification: 'not_verified',
    });
  });

  it('keeps the signed objects text verbatim and decodes bytes', () => {
    const mapped = toOpened(opened);
    expect(mapped.entries[0].objects).toBe('[{"a":1}]');
    expect(mapped.entries[0].signature).toHaveLength(64);
    expect(mapped.entries[0].storedTypes).toEqual(['consent.json']);
    expect(mapped.keys[0].wrap).toBeNull();
    expect(mapped.windows[0].pauses[0]).toEqual({ at: 'p', reason: 'liveness', resumedAt: null });
  });

  it('refuses a malformed body', () => {
    expect(() => toOpened({ conversation: {} })).toThrow();
    expect(() =>
      toOpened({ ...opened, entries: [{ ...opened.entries[0], signature: b(2, 63) }] })
    ).toThrow();
  });

  it('maps the trust body into ceremony facts for the tenant', () => {
    const trust = toTrust(
      {
        recovery_key: { key_id: ID, transcript_hash: b(9, 32) },
        ceremony: {
          ceremony_id: ID,
          k: 2,
          gateway_keys: [{ key_id: 'gk-1', public_key: toBase64Url(publicPoint(9n)) }],
          participants: [
            {
              holder_index: 1,
              holder_ref: 'anna',
              kind: 'custodian',
              display_name: 'Anna',
              enc_pub: toBase64Url(publicPoint(1n)),
              sig_pub: toBase64Url(publicPoint(2n)),
              fingerprint: b(1, 32),
            },
          ],
          dealings: [
            {
              dealer_index: 1,
              commitments: [toBase64Url(publicPoint(4n))],
              c: b(6, 32),
              s: b(7, 32),
              signature: b(8, 64),
            },
          ],
          transcript_signatures: [{ holder_index: 1, signature: b(5, 64) }],
        },
      },
      'tenant-kassel'
    );
    expect(trust.facts.tenantId).toBe('tenant-kassel');
    expect(trust.facts.gatewayKeys[0].keyId).toBe('gk-1');
    expect(trust.signatures.get(1)).toHaveLength(64);
    expect(() =>
      toTrust(
        { recovery_key: { key_id: 'x', transcript_hash: b(1, 31) }, ceremony: {} },
        'tenant-kassel'
      )
    ).toThrow();
  });
});
