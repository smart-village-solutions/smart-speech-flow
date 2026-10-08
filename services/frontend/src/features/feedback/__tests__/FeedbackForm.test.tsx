import { useState } from 'react';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { FeedbackAnswers, FeedbackFormDefinition } from '@/domain/feedback/feedbackForm.types';
import { createStubFeedbackSink } from '@/domain/feedback/StubFeedbackSink';
import { FeedbackForm } from '@/features/feedback/FeedbackForm';
import { FeedbackSheet } from '@/features/feedback/FeedbackSheet';

const FORM: FeedbackFormDefinition = {
  headline: 'Tell us',
  button: 'Send it',
  notice: { kind: 'lines', lines: [{ id: 'why', text: 'Why we ask' }] },
  questions: [
    {
      id: 'ease',
      type: 'rating',
      headline: 'Ease',
      question: 'How easy?',
      required: true,
      min: 1,
      max: 7,
    },
    {
      id: 'note',
      type: 'longText',
      headline: 'Note',
      question: 'Anything?',
      required: true,
      maxLength: 20,
      placeholder: 'Write',
    },
    {
      id: 'extra',
      type: 'scale',
      headline: 'Extra',
      question: 'Optional?',
      required: false,
      min: 1,
      max: 3,
    },
  ],
};

function Harness() {
  const [answers, setAnswers] = useState<FeedbackAnswers>({});
  return (
    <FeedbackForm
      definition={FORM}
      answers={answers}
      onChange={setAnswers}
      onSubmit={vi.fn()}
      status="idle"
      reasonKey={null}
    />
  );
}

const send = () => screen.getByRole('button', { name: 'Send it' });

describe('FeedbackForm', () => {
  it('renders every question of its definition as a group, with its notice and button', () => {
    renderWithProviders(<Harness />);

    for (const name of ['Ease', 'Note', 'Extra']) {
      expect(screen.getByRole('group', { name })).toBeInTheDocument();
    }
    expect(screen.getByText('Why we ask')).toBeInTheDocument();
    expect(send()).toBeDisabled();
  });

  it('cannot be submitted until every required question is answered', async () => {
    renderWithProviders(<Harness />);

    await userEvent.click(
      within(screen.getByRole('group', { name: 'Ease' })).getByRole('button', { name: '6 stars' })
    );
    expect(send()).toBeDisabled();

    await userEvent.type(screen.getByPlaceholderText('Write'), '   ');
    expect(send()).toBeDisabled();

    await userEvent.type(screen.getByPlaceholderText('Write'), 'fine');
    expect(send()).toBeEnabled();
  });
});

describe('the bundled form in Arabic', () => {
  it('renders right to left with every question named in Arabic', () => {
    renderWithProviders(<FeedbackSheet open onOpenChange={vi.fn()} />, {
      locale: 'ar',
      services: { feedback: createStubFeedbackSink() },
    });

    expect(document.documentElement).toHaveAttribute('dir', 'rtl');
    expect(screen.getByRole('dialog', { name: 'شاركنا ملاحظاتك' })).toBeInTheDocument();
    for (const name of [
      'جودة الترجمة',
      'الأداء',
      'الواجهة وسهولة الاستخدام',
      'التوصية',
      'أفكار للتحسين',
    ]) {
      expect(screen.getByRole('group', { name })).toBeInTheDocument();
    }
    expect(screen.getByRole('group', { name: 'التوصية' })).toHaveAccessibleDescription('مطلوب');
    expect(screen.getByRole('group', { name: 'أفكار للتحسين' })).toHaveAccessibleDescription('');
    expect(screen.getByText('غير محتمل إطلاقًا').nextElementSibling).toHaveTextContent(
      'محتمل جدًا'
    );
    expect(screen.getByRole('button', { name: 'إرسال الملاحظات' })).toBeDisabled();
  });
});
