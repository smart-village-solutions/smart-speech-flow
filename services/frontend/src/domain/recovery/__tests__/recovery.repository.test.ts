import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminAccessToken } from '@/app/auth/keycloak';
import { readConfig } from '@/app/config/env';
import { scalarToBytes, toBase64Url } from '@/core/crypto/bytes';
import { publicPoint } from '@/core/crypto/curve';
import { createHttpClient } from '@/core/http/client';
import { AppError } from '@/core/http/AppError';
import { createRecoveryCeremonyRepository } from '@/domain/recovery/recovery.repository';
import { server } from '@/test/setup';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

const BASE = 'http://api.test';
const CEREMONY = '0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a';
const URL = `${BASE}/api/admin/recording/ceremony`;
const b64 = (bytes: Uint8Array) => toBase64Url(bytes);

function repository() {
  return createRecoveryCeremonyRepository(createHttpClient(readConfig({ VITE_API_BASE_URL: BASE }), () => 'de'));
}

const ceremonyBody = {
  ceremony_id: CEREMONY,
  k: 2,
  status: 'confirming',
  started_by: 'olga',
  started_at: '2026-10-26T09:00:00+00:00',
  expires_at: '2026-10-27T09:00:00+00:00',
  gateway_keys: [{ key_id: 'gk-1', public_key: b64(publicPoint(9n)) }],
  participants: [
    {
      holder_index: 1,
      holder_ref: 'anna',
      kind: 'custodian',
      display_name: 'Anna',
      enc_pub: b64(publicPoint(1n)),
      sig_pub: b64(publicPoint(2n)),
      fingerprint: b64(new Uint8Array(32).fill(1)),
    },
    {
      holder_index: 2,
      holder_ref: 'paper-1',
      kind: 'paper',
      display_name: null,
      enc_pub: b64(publicPoint(3n)),
      sig_pub: null,
      fingerprint: b64(new Uint8Array(32).fill(2)),
    },
  ],
  dealings: [
    {
      dealer_index: 1,
      commitments: [b64(publicPoint(4n)), b64(publicPoint(5n))],
      c: b64(scalarToBytes(6n)),
      s: b64(scalarToBytes(7n)),
      signature: b64(new Uint8Array(64).fill(8)),
    },
  ],
  confirmed: [1],
  paper_confirmed: false,
  transcript_hash: b64(new Uint8Array(32).fill(9)),
};

describe('recovery ceremony repository', () => {
  beforeEach(() => {
    vi.mocked(getAdminAccessToken).mockReset().mockResolvedValue('staff-token');
  });

  it('reads a ceremony in progress into bytes and scalars', async () => {
    server.use(http.get(URL, () => HttpResponse.json({ recovery_key: null, ceremony: ceremonyBody })));
    const { ceremony, recoveryKey } = await repository().state();
    expect(recoveryKey).toBeNull();
    expect(ceremony?.participants.map((p) => [p.kind, p.sigPub === null])).toEqual([
      ['custodian', false],
      ['paper', true],
    ]);
    expect(ceremony?.dealings[0].proof).toEqual({ c: 6n, s: 7n });
    expect(Array.from(ceremony?.transcriptHash ?? [])).toEqual(Array(32).fill(9));
  });

  it('sends a dealing in the gateway wire form', async () => {
    let sent: Record<string, unknown> = {};
    server.use(
      http.post(`${URL}/${CEREMONY}/dealings`, async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ status: 'dealing' }, { status: 201 });
      })
    );
    await repository().deal(CEREMONY, {
      commitments: [publicPoint(4n)],
      proof: { c: 6n, s: 7n },
      signature: new Uint8Array(64),
      subshares: new Map([
        [1, '{"v":1}'],
        [2, '{"v":2}'],
      ]),
    });
    expect(sent).toEqual({
      commitments: [b64(publicPoint(4n))],
      c: b64(scalarToBytes(6n)),
      s: b64(scalarToBytes(7n)),
      signature: b64(new Uint8Array(64)),
      subshares: { '1': '{"v":1}', '2': '{"v":2}' },
    });
  });

  it('maps received sub-shares by holder and dealer', async () => {
    server.use(
      http.get(`${URL}/${CEREMONY}/subshares`, () => HttpResponse.json({ subshares: { '2': { '1': 'a', '3': 'b' } } }))
    );
    const received = await repository().subshares(CEREMONY);
    expect(received.get(2)?.get(3)).toBe('b');
  });

  it('surfaces the step-up code when starting', async () => {
    server.use(
      http.post(URL, () =>
        HttpResponse.json({ detail: { error_code: 'STEP_UP_REQUIRED', message: 'x' } }, { status: 403 })
      )
    );
    const started = repository().start(2, ['anna', 'bernd', 'carla'], null);
    await expect(started).rejects.toBeInstanceOf(AppError);
    await expect(started).rejects.toMatchObject({ serverCode: 'STEP_UP_REQUIRED' });
  });
});
