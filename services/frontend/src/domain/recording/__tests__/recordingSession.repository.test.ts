import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminAccessToken } from '@/app/auth/keycloak';
import { readConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { toRecordingRequest, toRecordingStatus } from '@/domain/recording/recordingSession.mapper';
import { createRecordingSessionRepository } from '@/domain/recording/recordingSession.repository';
import { server } from '@/test/setup';

vi.mock('@/app/auth/keycloak', () => ({ getAdminAccessToken: vi.fn() }));

const BASE = 'http://api.test';
const SINCE = '2026-10-27T12:00:00+00:00';
const asking = {
  state: 'asking',
  reason: null,
  window_id: null,
  state_version: 1,
  since: SINCE,
  request_id: 'r-1',
  consent_kind: 'first',
};

function repository() {
  return createRecordingSessionRepository(
    createHttpClient(readConfig({ VITE_API_BASE_URL: BASE }), () => 'de')
  );
}

describe('recording session repository', () => {
  beforeEach(() => {
    vi.mocked(getAdminAccessToken).mockReset().mockResolvedValue('staff-token');
  });

  it('reads the admin view with its open request and availability', async () => {
    server.use(
      http.get(`${BASE}/api/admin/session/S1/recording`, () =>
        HttpResponse.json({
          ...asking,
          can_request: true,
          unavailable_reason: null,
          next_consent_kind: 'resume',
          id_check: 'required',
        })
      )
    );
    const view = await repository().adminView('S1');
    expect(view.status).toEqual({
      phase: 'asking',
      reason: null,
      windowId: null,
      stateVersion: 1,
      since: Date.parse(SINCE),
    });
    expect(view.request).toEqual({ requestId: 'r-1', consentKind: 'first' });
    expect(view.canRequest).toBe(true);
    expect([view.nextConsentKind, view.idCheck]).toEqual(['resume', 'required']);
  });

  it('posts a request with its id and answers with the state', async () => {
    let body: unknown;
    server.use(
      http.post(`${BASE}/api/admin/session/S1/recording/request`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(asking);
      })
    );
    const state = await repository().request('S1', 'r-1');
    expect(body).toEqual({ request_id: 'r-1' });
    expect(state.phase).toBe('asking');

    await repository().request('S1', 'r-2', { guestName: 'Amira', idChecked: false });
    expect(body).toEqual({ request_id: 'r-2', guest_name: 'Amira', id_checked: false });
  });

  it("reads the open question's consent text and names its read-aloud clip", async () => {
    server.use(
      http.get(`${BASE}/api/customer/session/S1/recording/consent`, () =>
        HttpResponse.json({
          request_id: 'r-1',
          consent_kind: 'first',
          language: 'ar',
          html: '<p>نص</p>',
          signature: 'optional',
          proposed_name: 'Amira',
        })
      )
    );
    expect(await repository().consentText('S1')).toEqual({
      requestId: 'r-1',
      consentKind: 'first',
      language: 'ar',
      html: '<p>نص</p>',
      signature: 'optional',
      proposedName: 'Amira',
    });
    expect(repository().consentAudioUrl('S1', 'r 1', 'ab')).toBe(
      '/api/customer/session/S1/recording/consent/audio?request_id=r+1&text_sha256=ab'
    );
  });

  it('sends the guest answer and stops for either role', async () => {
    let answered: unknown;
    const off = { ...asking, state: 'off', reason: 'stopped_by_guest', state_version: 4 };
    server.use(
      http.post(`${BASE}/api/customer/session/S1/recording/answer`, async ({ request }) => {
        answered = await request.json();
        return HttpResponse.json({ ...asking, state: 'arming', state_version: 2 });
      }),
      http.post(`${BASE}/api/customer/session/S1/recording/stop`, () => HttpResponse.json(off)),
      http.post(`${BASE}/api/admin/session/S1/recording/stop`, () => HttpResponse.json(off))
    );
    expect((await repository().answer('S1', 'r-1', false)).phase).toBe('arming');
    expect(answered).toEqual({ request_id: 'r-1', consent: false });
    await repository().answer('S1', 'r-1', true, {
      textSha256: 'ab',
      name: 'Amira',
      signaturePng: 'iVBO',
      cannotSign: false,
    });
    expect(answered).toEqual({
      request_id: 'r-1',
      consent: true,
      text_sha256: 'ab',
      name: 'Amira',
      signature_png: 'iVBO',
      cannot_sign: false,
    });
    expect((await repository().stop('S1', 'customer')).reason).toBe('stopped_by_guest');
    expect((await repository().stop('S1', 'admin')).stateVersion).toBe(4);
  });

  it('refuses a body that is not a recording state', async () => {
    server.use(
      http.post(`${BASE}/api/admin/session/S1/recording/stop`, () =>
        HttpResponse.json({ state: 'recording' })
      )
    );
    await expect(repository().stop('S1', 'admin')).rejects.toThrow();
  });
});

describe('recording frames', () => {
  it("reports a playback to the role's own route", async () => {
    let reported: unknown;
    server.use(
      http.post(`${BASE}/api/customer/session/S1/recording/playback`, async ({ request }) => {
        reported = await request.json();
        return new HttpResponse(null, { status: 204 });
      })
    );

    await repository().reportPlayback('S1', 'customer', 'm-1', 'completed');

    expect(reported).toEqual({ message_id: 'm-1', event: 'completed' });
  });

  it('maps a state frame and drops a malformed one', () => {
    expect(toRecordingStatus({ ...asking, role: 'recording_state' })?.stateVersion).toBe(1);
    expect(toRecordingStatus({ ...asking, state_version: -1 })).toBeNull();
    expect(toRecordingStatus({ ...asking, since: 'yesterday' })).toBeNull();
  });

  it('maps a request frame', () => {
    expect(toRecordingRequest({ request_id: 'r-2', consent_kind: 'resume' })).toEqual({
      requestId: 'r-2',
      consentKind: 'resume',
    });
    expect(toRecordingRequest({ request_id: '', consent_kind: 'first' })).toBeNull();
  });
});
