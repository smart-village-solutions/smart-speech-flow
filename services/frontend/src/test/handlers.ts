import { http, HttpResponse } from 'msw';

export const SESSION_ID = 'A1B2C3D4';

export const handlers = [
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

  http.delete('*/api/admin/session/:id/terminate', ({ params }) =>
    HttpResponse.json({
      message: `Session ${String(params.id)} erfolgreich beendet`,
      session_id: params.id,
      status: 'terminated',
      timestamp: '2026-08-26T12:30:00+00:00',
    })
  ),

  http.get('*/api/session/:id', ({ params }) =>
    HttpResponse.json({
      id: params.id,
      customer_language: null,
      admin_language: 'de',
      status: 'pending',
      created_at: '2026-08-21T10:00:00+00:00',
      message_count: 0,
      admin_connected: true,
      customer_connected: false,
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

  http.get('*/api/session/:id/messages', ({ params }) =>
    HttpResponse.json({ session_id: params.id, messages: [] })
  ),

  http.post('*/api/session/:id/message', ({ params }) =>
    HttpResponse.json({
      status: 'success',
      message_id: 'm1',
      session_id: params.id,
      original_text: 'hello',
      translated_text: 'hallo',
      audio_available: true,
      audio_url: '/api/audio/m1.wav',
      processing_time_ms: 1200,
      pipeline_type: 'text',
    })
  ),

  http.post('*/api/session/:id/activity', () => HttpResponse.json({ status: 'ok' })),
];
