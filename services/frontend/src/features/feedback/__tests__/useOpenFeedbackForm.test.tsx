import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { toPublicContent } from '@/domain/content/content.mapper';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import { contentKeys } from '@/features/content/contentQuery';
import { useOpenFeedbackForm } from '@/features/feedback/useOpenFeedbackForm';
import { GuestContentSettled } from '@/test/ContentSettled';
import { installationBody } from '@/test/contentFixtures';
import { holdGuestContent } from '@/test/handlers';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';

const GUEST: FeedbackOrigin = { kind: 'guest', sessionId: 'A1B2C3D4' };

/** Installation content with a new revision whose form has another headline. */
const republished = toPublicContent({
  ...installationBody,
  revision: 'sha256:republished',
  feedback: { ...installationBody.feedback, headline: 'Neue Umfrage' },
});

interface ProbeProps {
  origin: FeedbackOrigin;
  waitMs?: number;
}

function Probe({ origin, waitMs }: Readonly<ProbeProps>) {
  const [open, setOpen] = useState(false);
  const { form, release } = useOpenFeedbackForm(origin, open, waitMs);
  const queryClient = useQueryClient();

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        open
      </button>
      <button
        type="button"
        onClick={() => {
          setOpen(false);
          release();
        }}
      >
        close
      </button>
      <button
        type="button"
        onClick={() => queryClient.setQueryData(contentKeys.public, republished)}
      >
        publish
      </button>
      <output aria-label="form">
        {form ? `${form.formSource}: ${form.definition.headline}` : 'none'}
      </output>
    </>
  );
}

const shown = () => screen.getByLabelText('form');
const click = (name: string) => userEvent.click(screen.getByRole('button', { name }));

describe('useOpenFeedbackForm', () => {
  it('freezes nothing while the sheet is closed', () => {
    renderWithProviders(<Probe origin={{ kind: 'public' }} />, { locale: 'de' });

    expect(shown()).toHaveTextContent('none');
  });

  it('freezes the form at once when content is already there', async () => {
    renderWithProviders(<Probe origin={{ kind: 'public' }} />, { locale: 'de' });

    await click('open');

    expect(shown()).toHaveTextContent('studio: Feedback geben');
  });

  it('waits for content still loading, then freezes Studio’s form', async () => {
    const held = holdGuestContent();
    server.use(held.handler);
    renderWithProviders(
      <>
        <Probe origin={GUEST} />
        <GuestContentSettled sessionId="A1B2C3D4" language="en" />
      </>
    );

    await click('open');
    expect(shown()).toHaveTextContent('none');

    held.release();

    expect(await screen.findByText('studio: Share your feedback')).toBeInTheDocument();
  });

  it('settles for the bundled form after the wait and keeps it when content lands', async () => {
    const held = holdGuestContent();
    server.use(held.handler);
    renderWithProviders(
      <>
        <Probe origin={GUEST} waitMs={50} />
        <GuestContentSettled sessionId="A1B2C3D4" language="en" />
      </>
    );

    await click('open');
    expect(await screen.findByText('bundled: Share your feedback')).toBeInTheDocument();

    held.release();
    await screen.findByTestId('guest-content-settled');

    expect(shown()).toHaveTextContent('bundled: Share your feedback');
  });

  it('keeps the frozen form when a new revision arrives', async () => {
    renderWithProviders(<Probe origin={{ kind: 'public' }} />, { locale: 'de' });

    await click('open');
    await click('publish');

    expect(shown()).toHaveTextContent('studio: Feedback geben');
  });

  it('resolves afresh on the next opening', async () => {
    renderWithProviders(<Probe origin={{ kind: 'public' }} />, { locale: 'de' });

    await click('open');
    await click('publish');
    await click('close');
    await click('open');

    expect(shown()).toHaveTextContent('studio: Neue Umfrage');
  });
});
