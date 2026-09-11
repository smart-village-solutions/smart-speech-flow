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

const SUBMISSION: FeedbackSubmission = {
  translationQuality: 4,
  performance: 5,
  usability: 3,
  netPromoterScore: 9,
  improvements: 'more languages',
  sessionId: 'A1B2C3D4',
};

function accept(capture?: (body: Record<string, unknown>) => void) {
  server.use(
    http.post('http://api.test/api/feedback', async ({ request }) => {
      capture?.((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(
        { feedback_id: '11111111-2222-3333-4444-555555555555' },
        { status: 201 }
      );
    })
  );
}

function reject(status: number) {
  server.use(
    http.post('http://api.test/api/feedback', () => new HttpResponse(null, { status }))
  );
}

describe('feedback repository', () => {
  it('sends the submission as the gateway snake_case contract', async () => {
    let body: Record<string, unknown> = {};
    accept((captured) => {
      body = captured;
    });

    await repository.submit(SUBMISSION);

    expect(body).toEqual({
      session_id: 'A1B2C3D4',
      translation_quality: 4,
      performance: 5,
      usability: 3,
      net_promoter_score: 9,
      improvements: 'more languages',
      form_version: 'v1',
    });
  });

  it('sends no field the gateway does not declare', async () => {
    // FeedbackSubmissionRequest is extra="forbid": an unexpected key is a
    // trust-boundary probe there and answers 422, not a silent drop.
    let body: Record<string, unknown> = {};
    accept((captured) => {
      body = captured;
    });

    await repository.submit(SUBMISSION);

    expect(Object.keys(body).sort()).toEqual([
      'form_version',
      'improvements',
      'net_promoter_score',
      'performance',
      'session_id',
      'translation_quality',
      'usability',
    ]);
  });

  it('sends null rather than an empty string when nothing was written', async () => {
    let body: Record<string, unknown> = {};
    accept((captured) => {
      body = captured;
    });

    await repository.submit({ ...SUBMISSION, improvements: '   ' });

    expect(body.improvements).toBeNull();
  });

  it('sends a null session for feedback offered outside any session', async () => {
    let body: Record<string, unknown> = {};
    accept((captured) => {
      body = captured;
    });

    await repository.submit({ ...SUBMISSION, sessionId: null });

    expect(body.session_id).toBeNull();
  });

  it('resolves on 201 without exposing the response to callers', async () => {
    accept();

    await expect(repository.submit(SUBMISSION)).resolves.toBeUndefined();
  });

  it.each([
    [404, 'notFound'],
    [422, 'validation'],
    [503, 'server'],
  ])('surfaces %i as an AppError the sheet can translate', async (status, kind) => {
    reject(status);

    await expect(repository.submit(SUBMISSION)).rejects.toMatchObject({
      name: 'AppError',
      kind,
    });
  });

  it('surfaces a lost connection as an AppError, not a raw axios failure', async () => {
    server.use(http.post('http://api.test/api/feedback', () => HttpResponse.error()));

    const error = await repository.submit(SUBMISSION).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(AppError);
  });
});
