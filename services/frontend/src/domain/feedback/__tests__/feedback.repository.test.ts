import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/setup';
import { readConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { AppError } from '@/core/http/AppError';
import { createFeedbackRepository } from '@/domain/feedback/feedback.repository';
import type { FeedbackSubmission } from '@/domain/feedback/feedback.types';

const config = readConfig({ VITE_API_BASE_URL: 'http://api.test' });
const repository = createFeedbackRepository(createHttpClient(config, () => 'en'));

const REVISION = 'sha256:302a620a286580ceae9a5e0404c71c97b79c42a023b479a979e41475b309e60e';
const ANSWERS = { translationQuality: 4, recommendation: 9, improvementIdeas: 'more languages' };

const GUEST: FeedbackSubmission = {
  audience: 'guest',
  sessionId: 'A1B2C3D4',
  locale: 'en',
  formSource: 'studio',
  revision: REVISION,
  answers: ANSWERS,
};

type Captured = { path: string; body: Record<string, unknown> };

/** Answers both submit routes and records which one was asked, with what. */
function accept(): Captured[] {
  const captured: Captured[] = [];
  const record = async ({ request }: { request: Request }) => {
    captured.push({
      path: new URL(request.url).pathname,
      body: (await request.json()) as Record<string, unknown>,
    });
    return HttpResponse.json(
      { feedback_id: '11111111-2222-3333-4444-555555555555' },
      { status: 201 }
    );
  };
  server.use(
    http.post('http://api.test/api/feedback', record),
    http.post('http://api.test/api/admin/feedback', record)
  );
  return captured;
}

function reject(status: number, errorCode?: string) {
  server.use(
    http.post('http://api.test/api/feedback', () =>
      errorCode === undefined
        ? new HttpResponse(null, { status })
        : HttpResponse.json(
            { detail: { error_code: errorCode, message: 'fixed text' } },
            { status }
          )
    )
  );
}

describe('feedback repository', () => {
  it('sends guest feedback with its session to /api/feedback, key by key', async () => {
    const captured = accept();

    await repository.submit(GUEST);

    expect(captured).toEqual([
      {
        path: '/api/feedback',
        body: {
          audience: 'guest',
          session_id: 'A1B2C3D4',
          locale: 'en',
          form_source: 'studio',
          configuration_revision: REVISION,
          answers: ANSWERS,
        },
      },
    ]);
  });

  it('sends installation feedback with no session_id at all', async () => {
    // The gateway refuses a session on installation feedback (422).
    const captured = accept();

    await repository.submit({
      ...GUEST,
      audience: 'installation',
      sessionId: null,
      locale: 'de-DE',
    });

    expect(captured[0].path).toBe('/api/feedback');
    expect(Object.keys(captured[0].body).sort((a, b) => a.localeCompare(b))).toEqual([
      'answers',
      'audience',
      'configuration_revision',
      'form_source',
      'locale',
    ]);
  });

  it('sends staff feedback from a session to /api/admin/feedback with that session', async () => {
    const captured = accept();

    await repository.submit({
      ...GUEST,
      audience: 'staff',
      sessionId: 'E5F6G7H8',
      locale: 'de-DE',
    });

    expect(captured).toEqual([
      {
        path: '/api/admin/feedback',
        body: expect.objectContaining({ audience: 'staff', session_id: 'E5F6G7H8' }),
      },
    ]);
  });

  it('sends staff feedback from the dashboard to /api/admin/feedback without a session', async () => {
    const captured = accept();

    await repository.submit({ ...GUEST, audience: 'staff', sessionId: null, locale: 'de-DE' });

    expect(captured[0].path).toBe('/api/admin/feedback');
    expect(captured[0].body).not.toHaveProperty('session_id');
  });

  it('sends a null revision for the bundled form', async () => {
    const captured = accept();

    await repository.submit({ ...GUEST, formSource: 'bundled', revision: null });

    expect(captured[0].body).toMatchObject({
      form_source: 'bundled',
      configuration_revision: null,
    });
  });

  it('resolves on 201 without exposing the response to callers', async () => {
    accept();

    await expect(repository.submit(GUEST)).resolves.toBeUndefined();
  });

  it('names a changed form by its error code, and offers no retry', async () => {
    reject(409, 'feedback_form_changed');

    await expect(repository.submit(GUEST)).rejects.toMatchObject({
      name: 'AppError',
      serverCode: 'feedback_form_changed',
      retryable: false,
    });
  });

  it.each([
    [404, undefined, 'notFound', false],
    [422, 'feedback_request_invalid', 'validation', false],
    [503, 'feedback_form_unavailable', 'server', true],
  ])(
    'surfaces %i (%s) as an AppError the sheet can translate',
    async (status, code, kind, retryable) => {
      reject(status, code);

      await expect(repository.submit(GUEST)).rejects.toMatchObject({
        name: 'AppError',
        kind,
        retryable,
      });
    }
  );

  it('surfaces a lost connection as an AppError, not a raw axios failure', async () => {
    server.use(http.post('http://api.test/api/feedback', () => HttpResponse.error()));

    const error = await repository.submit(GUEST).catch((error_: unknown) => error_);

    expect(error).toBeInstanceOf(AppError);
  });
});
