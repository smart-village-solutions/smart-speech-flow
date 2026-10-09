import { http, HttpResponse, type JsonBodyType } from 'msw';
import {
  GUEST_LANGUAGE_CODES,
  INSTALLATION_ETAG,
  guestContentBody,
  guestLanguagesBody,
  installationBody,
  staffContentBody,
} from './contentFixtures';

export const SESSION_ID = 'A1B2C3D4';

export const GUEST_LANGUAGES_ROUTE = '*/api/customer/session/:id/languages';
const GUEST_CONTENT_ROUTE = '*/api/customer/session/:id/content/:language';

const isGuestLanguage = (language: string) =>
  (GUEST_LANGUAGE_CODES as readonly string[]).includes(language);

/** The content route: `respond` for the nine guest languages, the gateway's 404 for any other. */
export function guestContentHandler(respond: (language: string) => Response | Promise<Response>) {
  return http.get(GUEST_CONTENT_ROUTE, ({ params }) => {
    const language = String(params.language);
    return isGuestLanguage(language)
      ? respond(language)
      : HttpResponse.json({ detail: 'Language not supported' }, { status: 404 });
  });
}

export function guestLanguagesHandler(body: JsonBodyType) {
  return http.get(GUEST_LANGUAGES_ROUTE, () => HttpResponse.json(body));
}

/** Holds every content request until `release`, for the wait and timeout cases. */
export function holdGuestContent() {
  let release!: () => void;
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  const handler = guestContentHandler(async (language) => {
    await released;
    return HttpResponse.json(guestContentBody(language));
  });
  return { handler, release };
}

const STAFF_CONTENT_ROUTE = '*/api/admin/content';

export function staffContentHandler(body: JsonBodyType) {
  return http.get(STAFF_CONTENT_ROUTE, () => HttpResponse.json(body));
}

/** Studio's login directory down past its cache: every /api/admin route answers 503. */
export function staffContentUnavailable() {
  return http.get(STAFF_CONTENT_ROUTE, () =>
    HttpResponse.json({ detail: 'Studio content is temporarily unavailable' }, { status: 503 })
  );
}

export const handlers = [
  http.get('*/api/login/tenants', () =>
    HttpResponse.json({
      tenants: [
        { id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025', studioUrl: 'https://fulda.dialog.kassel.de/' },
        { id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025', studioUrl: 'https://smartcity.dialog.kassel.de/' },
      ],
    })
  ),

  http.get('*/api/health/summary', () =>
    HttpResponse.json({
      status: 'success',
      overall_healthy: true,
      summary: {
        service_mode: 'full',
        circuit_states: { asr: 'closed', translation: 'closed', tts: 'closed' },
        gpu: { critical_devices: 0, warning_devices: 0, recommended_action: 'steady' },
      },
    })
  ),

  http.post('*/api/admin/session/create', () =>
    HttpResponse.json(
      {
        session_id: SESSION_ID,
        client_url: `http://localhost:5173/join/${SESSION_ID}`,
        status: 'pending',
        created_at: '2026-08-26T12:00:00+00:00',
        message: `Session ${SESSION_ID} erfolgreich erstellt.`,
      },
      { status: 201 }
    )
  ),

  // Deliberately out of order, with the live session in the second array, so
  // anything that renders this also exercises the merge.
  http.get('*/api/admin/session/history', () =>
    HttpResponse.json({
      sessions: [
        {
          id: 'TR000001',
          customer_language: 'tr',
          admin_language: 'de',
          status: 'terminated',
          created_at: '2026-08-26T09:00:00+00:00',
          terminated_at: '2026-08-26T09:14:00+00:00',
          message_count: 12,
          admin_connected: false,
          customer_connected: false,
        },
        {
          id: 'RU000001',
          customer_language: 'ru',
          admin_language: 'de',
          status: 'terminated',
          created_at: '2026-08-26T07:30:00+00:00',
          terminated_at: '2026-08-26T08:01:00+00:00',
          message_count: 31,
          admin_connected: false,
          customer_connected: false,
        },
      ],
      total_count: 2,
      active_sessions: [
        {
          id: 'AR000001',
          customer_language: 'ar',
          admin_language: 'de',
          status: 'active',
          created_at: '2026-08-26T11:20:00+00:00',
          terminated_at: null,
          message_count: 3,
          admin_connected: true,
          customer_connected: true,
        },
      ],
    })
  ),

  // The requesting admin's own live session: the live row of the history above.
  http.get('*/api/admin/session/current', () =>
    HttpResponse.json({
      session_id: 'AR000001',
      status: 'active',
      customer_language: 'ar',
      admin_connected: true,
      customer_connected: true,
      message_count: 3,
      created_at: '2026-08-26T11:20:00+00:00',
      terminated_at: null,
      termination_reason: null,
      warning_at: '2026-08-26T19:15:00+00:00',
      timeout_at: '2026-08-26T19:20:00+00:00',
    })
  ),

  http.delete('*/api/admin/session/:id/terminate', ({ params }) =>
    HttpResponse.json({
      message: `Session ${String(params.id)} erfolgreich beendet`,
      session_id: params.id,
      status: 'terminated',
      timestamp: '2026-08-26T12:30:00+00:00',
    })
  ),

  http.get('*/api/content/installation', () =>
    HttpResponse.json(installationBody, {
      headers: { ETag: INSTALLATION_ETAG, 'Cache-Control': 'public, max-age=60' },
    })
  ),

  guestLanguagesHandler(guestLanguagesBody),

  guestContentHandler((language) => HttpResponse.json(guestContentBody(language))),

  staffContentHandler(staffContentBody),

  // Shapes follow the gateway routes; a fixture that drifts from them hides mapper bugs.
  http.get('*/api/customer/session/:id', ({ params }) =>
    HttpResponse.json({
      session_id: params.id,
      status: 'pending',
      customer_language: null,
      admin_connected: true,
      customer_connected: false,
      is_active: false,
      can_send_messages: false,
      created_at: '2026-08-21T10:00:00+00:00',
      warning_at: '2026-08-21T10:25:00+00:00',
      timeout_at: '2026-08-21T10:30:00+00:00',
    })
  ),

  http.get('*/api/admin/session/:id/status', ({ params }) =>
    HttpResponse.json({
      session_id: params.id,
      status: 'pending',
      customer_language: null,
      admin_connected: true,
      customer_connected: false,
      message_count: 0,
      created_at: '2026-08-21T10:00:00+00:00',
      terminated_at: null,
      termination_reason: null,
      warning_at: '2026-08-21T10:25:00+00:00',
      timeout_at: '2026-08-21T10:30:00+00:00',
    })
  ),

  http.get('*/api/languages/supported', () =>
    HttpResponse.json({
      languages: {
        de: { name: 'Deutsch', native: 'Deutsch' },
        en: { name: 'English', native: 'English' },
        ar: { name: 'Arabic', native: 'العربية' },
        tr: { name: 'Turkish', native: 'Türkçe' },
        ru: { name: 'Russian', native: 'Русский' },
        uk: { name: 'Ukrainian', native: 'Українська' },
        am: { name: 'Amharic', native: 'አማርኛ' },
        ti: { name: 'Tigrinya', native: 'ትግርኛ' },
        ku: { name: 'Kurdish', native: 'Kurmancî' },
        fa: { name: 'Persian', native: 'فارسی' },
      },
      admin_default: 'de',
      popular: ['en', 'ar', 'tr', 'ru', 'fa'],
    })
  ),

  http.post('*/api/customer/session/activate', async ({ request }) => {
    const body = (await request.json()) as { session_id: string; customer_language: string };
    return HttpResponse.json({
      session_id: body.session_id,
      status: 'active',
      customer_language: body.customer_language,
      message: 'Session activated',
      timestamp: '2026-08-21T10:00:00+00:00',
    });
  }),

  http.get('*/api/:role/session/:id/messages', ({ params }) =>
    HttpResponse.json({ session_id: params.id, messages: [] })
  ),

  http.post('*/api/:role/session/:id/message', ({ params }) =>
    HttpResponse.json({
      status: 'success',
      message_id: 'm1',
      session_id: params.id,
      original_text: 'hello',
      translated_text: 'hallo',
      audio_available: true,
      audio_url: `/api/${String(params.role)}/session/${String(params.id)}/audio/m1/translated.wav`,
      processing_time_ms: 1200,
      pipeline_type: 'text',
    })
  ),
];
