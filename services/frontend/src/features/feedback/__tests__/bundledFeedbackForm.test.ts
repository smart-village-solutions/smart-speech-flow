import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/setup';
import { readConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { createFeedbackRepository } from '@/domain/feedback/feedback.repository';
import { toV1Submission } from '@/domain/feedback/feedback.mapper';
import type { FeedbackAnswers } from '@/domain/feedback/feedbackForm.types';
import { createI18n } from '@/i18n';
import { bundledFeedbackForm } from '@/features/feedback/bundledFeedbackForm';
import { isComplete } from '@/features/feedback/feedback.state';

const form = bundledFeedbackForm(createI18n('en').t);

describe('bundledFeedbackForm', () => {
  it("asks today's questions under Studio's ids, requiring what export 140 requires", () => {
    expect(form.questions.map(({ id, type, required }) => [id, type, required])).toEqual([
      ['translationQuality', 'rating', true],
      ['performance', 'rating', true],
      ['usability', 'rating', true],
      ['recommendation', 'scale', true],
      ['improvementIdeas', 'longText', false],
    ]);
  });

  it("keeps today's copy, ranges, end labels and text limit", () => {
    expect(form.headline).toBe('Share your feedback');
    expect(form.button).toBe('Send feedback');
    expect(form.questions[0]).toMatchObject({
      headline: 'Translation quality',
      question: 'How accurate were the translations?',
      min: 1,
      max: 5,
    });
    expect(form.questions[3]).toMatchObject({
      headline: 'Recommendation',
      min: 0,
      max: 10,
      minLabel: 'Not at all likely',
      maxLabel: 'Extremely likely',
    });
    expect(form.questions[4]).toMatchObject({
      placeholder: 'Your ideas, feature requests, or anything that bothered you…',
      maxLength: 4000,
    });
    expect(form.notice.lines.map((line) => line.text)).toEqual([
      'Your answers are used only to improve KasselDIALOG.',
      'We keep feedback for twelve months and delete it automatically after that.',
      'You can have your feedback withdrawn at any time — just ask a member of staff.',
    ]);
  });

  it('produces the v1 body byte for byte when answered as today', async () => {
    let raw = '';
    server.use(
      http.post('http://api.test/api/feedback', async ({ request }) => {
        raw = await request.text();
        return HttpResponse.json({ feedback_id: 'f1' }, { status: 201 });
      })
    );
    const answers: FeedbackAnswers = {
      translationQuality: 4,
      performance: 5,
      usability: 2,
      recommendation: 0,
      improvementIdeas: '  more languages ',
    };
    const repository = createFeedbackRepository(
      createHttpClient(readConfig({ VITE_API_BASE_URL: 'http://api.test' }), () => 'en')
    );

    expect(isComplete(form, answers)).toBe(true);
    await repository.submit(toV1Submission(answers, 'A1B2C3D4'));

    expect(raw).toBe(
      '{"session_id":"A1B2C3D4","translation_quality":4,"performance":5,"usability":2,' +
        '"net_promoter_score":0,"improvements":"more languages","form_version":"v1"}'
    );
  });
});
