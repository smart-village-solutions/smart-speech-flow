import { http, HttpResponse } from 'msw';

export const SESSION_ID = 'A1B2C3D4';

export const handlers = [
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
