import { HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { FeedbackOrigin } from '@/domain/feedback/feedback.types';
import { audienceOf } from '@/domain/feedback/feedbackOrigin';
import { useFeedbackForm } from '@/features/feedback/useFeedbackForm';
import { contentKeys } from '@/features/content/contentQuery';
import { GuestContentSettled, StaffContentSettled } from '@/test/ContentSettled';
import { KASSEL_REVISION } from '@/test/contentFixtures';
import { guestContentHandler, holdGuestContent, staffContentUnavailable } from '@/test/handlers';
import { recordRequests } from '@/test/recordRequests';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';

const GUEST: FeedbackOrigin = { kind: 'guest', sessionId: 'A1B2C3D4' };
const STAFF: FeedbackOrigin = { kind: 'staff', sessionId: null };

function Probe({ origin, active = true }: Readonly<{ origin: FeedbackOrigin; active?: boolean }>) {
  const { resolve, settled, contentKey } = useFeedbackForm(origin, active);
  const form = resolve();
  return (
    <output aria-label="form">
      {JSON.stringify({
        source: form.formSource,
        revision: form.revision,
        locale: form.locale,
        audience: audienceOf(form.origin),
        headline: form.definition.headline,
        settled,
        contentKey,
      })}
    </output>
  );
}

const read = () =>
  JSON.parse(screen.getByLabelText('form').textContent ?? '{}') as Record<string, unknown>;
const contentRequests = () =>
  recordRequests((request) =>
    /\/api\/(admin\/content|customer\/session\/[^/]+\/content)/.test(request.url)
  );

describe('useFeedbackForm', () => {
  it('reads the installation form from the seeded cache without a request', () => {
    const requests = contentRequests();
    renderWithProviders(<Probe origin={{ kind: 'public' }} />, { locale: 'de' });

    expect(read()).toMatchObject({
      source: 'studio',
      locale: 'de-DE',
      audience: 'installation',
      settled: true,
      contentKey: [...contentKeys.public],
    });
    expect(requests).toEqual([]);
  });

  it('is bundled and unsettled while guest content loads, then Studio once it arrives', async () => {
    const held = holdGuestContent();
    server.use(held.handler);
    renderWithProviders(
      <>
        <Probe origin={GUEST} />
        <GuestContentSettled sessionId="A1B2C3D4" language="en" />
      </>
    );

    expect(read()).toMatchObject({ source: 'bundled', settled: false });

    held.release();
    await screen.findByTestId('guest-content-settled');

    expect(read()).toMatchObject({
      source: 'studio',
      revision: KASSEL_REVISION,
      locale: 'en',
      audience: 'guest',
      settled: true,
      contentKey: [...contentKeys.guest('A1B2C3D4', 'en')],
    });
  });

  it('is bundled when guest content fails', async () => {
    server.use(guestContentHandler(() => new HttpResponse(null, { status: 503 })));
    renderWithProviders(
      <>
        <Probe origin={GUEST} />
        <GuestContentSettled sessionId="A1B2C3D4" language="en" />
      </>
    );
    await screen.findByTestId('guest-content-settled');

    expect(read()).toMatchObject({ source: 'bundled', revision: null, settled: true });
  });

  it('asks for no staff content outside staff screens', async () => {
    const requests = contentRequests();
    renderWithProviders(
      <>
        <Probe origin={GUEST} />
        <GuestContentSettled sessionId="A1B2C3D4" language="en" />
      </>
    );
    await screen.findByTestId('guest-content-settled');

    expect(requests.filter((url) => url.includes('/api/admin/'))).toEqual([]);
  });

  it('reads the staff form in the staff language', async () => {
    renderWithProviders(
      <>
        <Probe origin={STAFF} />
        <StaffContentSettled />
      </>,
      { locale: 'de' }
    );
    await screen.findByTestId('staff-content-settled');

    expect(read()).toMatchObject({
      source: 'studio',
      revision: KASSEL_REVISION,
      locale: 'de-DE',
      audience: 'staff',
      contentKey: [...contentKeys.staff],
    });
  });

  it('is bundled when staff content is unavailable', async () => {
    server.use(staffContentUnavailable());
    renderWithProviders(
      <>
        <Probe origin={STAFF} />
        <StaffContentSettled />
      </>,
      { locale: 'de' }
    );
    await screen.findByTestId('staff-content-settled');

    expect(read()).toMatchObject({ source: 'bundled', locale: 'de', audience: 'staff' });
  });

  it('asks for nothing while the sheet is closed', async () => {
    // A guest who closed the sheet may leave the session, and the screen's
    // locale may change; a live query would keep asking for content that 404s.
    const requests = contentRequests();
    renderWithProviders(<Probe origin={GUEST} active={false} />);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(requests).toEqual([]);
    expect(read()).toMatchObject({ settled: true });
  });
});
