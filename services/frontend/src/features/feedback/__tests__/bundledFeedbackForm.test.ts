import { readFileSync } from 'node:fs';
import path from 'node:path';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/setup';
import { readConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { createFeedbackRepository } from '@/domain/feedback/feedback.repository';
import { answeredOnly } from '@/domain/feedback/feedback.mapper';
import type {
  FeedbackAnswers,
  FeedbackQuestion,
} from '@/domain/feedback/feedbackForm.types';
import { createI18n } from '@/i18n';
import { bundledFeedbackForm } from '@/features/feedback/bundledFeedbackForm';
import { isComplete } from '@/features/feedback/feedback.state';

const form = bundledFeedbackForm(createI18n('en').t);

// The gateway validates bundled answers against the same file (feedback/bundled_form.py).
const gatewayRules: unknown = JSON.parse(
  readFileSync(
    path.join(import.meta.dirname, '../../../../../../tests/fixtures/feedback/bundled_form.json'),
    'utf8'
  )
);

function toRule(question: FeedbackQuestion) {
  const { id, type, required } = question;
  return question.type === 'longText'
    ? { id, type, required, maxLength: question.maxLength }
    : { id, type, required, min: question.min, max: question.max };
}

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

  it('asks exactly what the gateway accepts for a bundled submission', () => {
    expect(form.questions.map(toRule)).toEqual(gatewayRules);
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
    expect(form.notice.kind === 'lines' && form.notice.lines.map((line) => line.text)).toEqual([
      'Your answers are used only to improve KasselDIALOG.',
      'We keep feedback for twelve months and delete it automatically after that.',
      'You can have your feedback withdrawn at any time — just ask a member of staff.',
    ]);
  });

  it('produces the v2 bundled body byte for byte when answered as today', async () => {
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
    await repository.submit({
      audience: 'guest',
      sessionId: 'A1B2C3D4',
      locale: 'en',
      formSource: 'bundled',
      revision: null,
      answers: answeredOnly(form.questions, answers),
    });

    expect(raw).toBe(
      '{"audience":"guest","session_id":"A1B2C3D4","locale":"en","form_source":"bundled",' +
        '"configuration_revision":null,"answers":{"translationQuality":4,"performance":5,' +
        '"usability":2,"recommendation":0,"improvementIdeas":"more languages"}}'
    );
  });
});
