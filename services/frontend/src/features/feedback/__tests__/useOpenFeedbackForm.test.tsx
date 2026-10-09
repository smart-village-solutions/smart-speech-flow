import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
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

/** The installation route: ordinary reads answer at once, fresh reads (no-cache) wait for `settle`. */
function holdFreshInstallation(answer: () => Response) {
  let settle!: () => void;
  const settled = new Promise<void>((resolve) => {
    settle = resolve;
  });
  const handler = http.get('*/api/content/installation', async ({ request }) => {
    if (request.headers.get('Cache-Control') !== 'no-cache')
      return HttpResponse.json(installationBody);
    await settled;
    return answer();
  });
  return { handler, settle };
}

/** Like Probe, with a reload, a background refetch and a second origin to reopen from. */
function ReloadProbe({ waitMs }: Readonly<{ waitMs?: number }>) {
  const [origin, setOrigin] = useState<FeedbackOrigin>({ kind: 'public' });
  const [open, setOpen] = useState(false);
  const { form, release, reload } = useOpenFeedbackForm(origin, open, waitMs);
  const queryClient = useQueryClient();
  const actions: Record<string, () => void> = {
    open: () => setOpen(true),
    close: () => {
      setOpen(false);
      release();
    },
    reload: () => void reload(),
    refetch: () => void queryClient.refetchQueries({ queryKey: contentKeys.public }),
    guest: () => {
      setOrigin(GUEST);
      setOpen(true);
    },
  };

  return (
    <>
      {Object.entries(actions).map(([name, action]) => (
        <button key={name} type="button" onClick={action}>
          {name}
        </button>
      ))}
      <output aria-label="form">
        {form ? `${form.formSource} ${form.origin.kind}: ${form.definition.headline}` : 'none'}
      </output>
    </>
  );
}

describe('reloading a changed form', () => {
  it('never lets a reload from a closed opening land in the next one', async () => {
    const held = holdFreshInstallation(() => new HttpResponse(null, { status: 503 }));
    const guest = holdGuestContent();
    server.use(held.handler, guest.handler);
    renderWithProviders(
      <>
        <ReloadProbe waitMs={5_000} />
        <GuestContentSettled sessionId="A1B2C3D4" language="en" />
      </>
    );

    await click('open');
    await click('reload');
    await click('close');
    await click('guest');
    // The old reload fails while the guest opening is still waiting for its content.
    held.settle();
    await new Promise((resolve) => setTimeout(resolve, 50));
    guest.release();
    await screen.findByTestId('guest-content-settled');

    expect(await screen.findByText('studio guest: Share your feedback')).toBeInTheDocument();
  });

  it('gives up on a slow reload after the wait, with the bundled form', async () => {
    const held = holdFreshInstallation(() => HttpResponse.json(installationBody));
    server.use(held.handler);
    renderWithProviders(<ReloadProbe waitMs={50} />, { locale: 'de' });

    await click('open');
    await click('reload');

    try {
      expect(await screen.findByText('bundled public: Feedback geben')).toBeInTheDocument();
    } finally {
      held.settle();
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(shown()).toHaveTextContent('bundled public: Feedback geben');
  });

  it('falls back to the bundled form when the reload brings the revision it was refused on', async () => {
    // The gateway refused answers the client's rules accepted: reloading the
    // same revision would only lead to the same refusal.
    server.use(http.get('*/api/content/installation', () => HttpResponse.json(installationBody)));
    renderWithProviders(<ReloadProbe />, { locale: 'de' });

    await click('open');
    expect(shown()).toHaveTextContent('studio public: Feedback geben');
    await click('reload');

    expect(await screen.findByText('bundled public: Feedback geben')).toBeInTheDocument();
  });

  it('makes its own fresh read even while an ordinary refetch is in flight', async () => {
    let releaseOrdinary!: () => void;
    const ordinary = new Promise<void>((resolve) => {
      releaseOrdinary = resolve;
    });
    server.use(
      http.get('*/api/content/installation', async ({ request }) => {
        if (request.headers.get('Cache-Control') === 'no-cache') {
          return HttpResponse.json({
            ...installationBody,
            revision: 'sha256:republished',
            feedback: { ...installationBody.feedback, headline: 'Neue Umfrage' },
          });
        }
        await ordinary;
        return HttpResponse.json(installationBody);
      })
    );
    renderWithProviders(<ReloadProbe />, { locale: 'de' });

    await click('open');
    await click('refetch');
    await click('reload');

    try {
      expect(await screen.findByText('studio public: Neue Umfrage')).toBeInTheDocument();
    } finally {
      releaseOrdinary();
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  });
});
