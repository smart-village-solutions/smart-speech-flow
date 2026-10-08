import { useState } from 'react';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { FeedbackQuestion as Question } from '@/domain/feedback/feedbackForm.types';
import { FeedbackQuestion } from '@/features/feedback/FeedbackQuestion';

function Harness({ question }: Readonly<{ question: Question }>) {
  const [value, setValue] = useState<number | string | null>(null);
  return <FeedbackQuestion question={question} value={value} onChange={setValue} />;
}

const show = (question: Question) => renderWithProviders(<Harness question={question} />);

const SPEED: Question = {
  id: 'speed',
  type: 'rating',
  headline: 'Speed',
  question: 'How fast was it?',
  required: true,
  min: 1,
  max: 5,
};

describe('FeedbackQuestion', () => {
  it('names the group after the headline and asks the question inside it', () => {
    show(SPEED);

    const group = screen.getByRole('group', { name: 'Speed' });
    expect(within(group).getByText('How fast was it?')).toBeInTheDocument();
  });

  it('names the group after the question when there is no headline', () => {
    show({
      id: 'r',
      type: 'scale',
      question: 'Would you recommend us?',
      required: false,
      min: 0,
      max: 10,
    });

    expect(screen.getByRole('group', { name: 'Would you recommend us?' })).toBeInTheDocument();
  });

  it('marks a required question without changing its name', () => {
    show(SPEED);

    expect(screen.getByRole('group', { name: 'Speed' })).toHaveAccessibleDescription('Required');
  });

  it('leaves an optional question unmarked', () => {
    show({ ...SPEED, required: false });

    expect(screen.getByRole('group', { name: 'Speed' })).toHaveAccessibleDescription('');
  });

  it('renders a 1-5 rating as five stars', () => {
    show(SPEED);

    expect(
      within(screen.getByRole('group', { name: 'Speed' })).getAllByRole('button')
    ).toHaveLength(5);
  });

  it('renders a 1-7 rating as seven stars and keeps the choice', async () => {
    show({ ...SPEED, max: 7 });

    const group = screen.getByRole('group', { name: 'Speed' });
    expect(within(group).getAllByRole('button')).toHaveLength(7);
    await userEvent.click(within(group).getByRole('button', { name: '7 stars' }));
    expect(within(group).getByRole('button', { name: '7 stars' })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
  });

  it('renders a 0-10 scale', () => {
    show({
      id: 'r',
      type: 'scale',
      headline: 'Recommend',
      question: 'Recommend us?',
      required: true,
      min: 0,
      max: 10,
    });

    const buttons = within(screen.getByRole('group', { name: 'Recommend' })).getAllByRole('button');
    expect(buttons.map((button) => button.textContent)).toEqual([
      '0',
      '1',
      '2',
      '3',
      '4',
      '5',
      '6',
      '7',
      '8',
      '9',
      '10',
    ]);
  });

  it('renders a 1-7 scale with its end labels', () => {
    show({
      id: 'ease',
      type: 'scale',
      headline: 'Ease',
      question: 'How easy was it?',
      required: true,
      min: 1,
      max: 7,
      minLabel: 'Hard',
      maxLabel: 'Easy',
    });

    const group = screen.getByRole('group', { name: 'Ease' });
    expect(
      within(group)
        .getAllByRole('button')
        .map((button) => button.textContent)
    ).toEqual(['1', '2', '3', '4', '5', '6', '7']);
    expect(within(group).getByText('Hard').nextElementSibling).toHaveTextContent('Easy');
  });

  it('limits long text to the maxLength of its question', async () => {
    show({
      id: 'ideas',
      type: 'longText',
      headline: 'Ideas',
      question: 'Anything else?',
      required: false,
      placeholder: 'Type here',
      maxLength: 12,
    });

    const field = within(screen.getByRole('group', { name: 'Ideas' })).getByPlaceholderText(
      'Type here'
    );
    expect(field).toHaveAttribute('maxlength', '12');
    await userEvent.type(field, 'more languages please');
    expect(field).toHaveValue('more languag');
  });
});
