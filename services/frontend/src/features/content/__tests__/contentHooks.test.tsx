import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/setup';
import { renderWithProviders } from '@/test/renderWithProviders';
import { recordRequests } from '@/test/recordRequests';
import type { ContentState } from '@/features/content/contentQuery';
import { usePublicContent } from '@/features/content/usePublicContent';
import { useGuestContent } from '@/features/content/useGuestContent';
import { useStaffContent } from '@/features/content/useStaffContent';

function describeState<T>(state: ContentState<T>, show: (content: T) => string): string {
  if (!state.settled) return 'pending';
  return state.content === undefined ? 'bundled' : show(state.content);
}

function Public() {
  return <output>{describeState(usePublicContent(), (content) => content.locale)}</output>;
}

function Guest({ sessionId, language }: Readonly<{ sessionId?: string; language?: string }>) {
  const state = useGuestContent(sessionId, language);
  return (
    <output>{describeState(state, (content) => `provided ${String(content.provided)}`)}</output>
  );
}

function Staff() {
  return <output>{describeState(useStaffContent(), (content) => String(content.timeZone))}</output>;
}

describe('content hooks', () => {
  it('read installation content', async () => {
    renderWithProviders(<Public />);

    expect(screen.getByText('pending')).toBeInTheDocument();
    expect(await screen.findByText('de-DE')).toBeInTheDocument();
  });

  it.each([
    ['a 503', () => HttpResponse.json({ detail: 'unavailable' }, { status: 503 })],
    ['a network error', () => HttpResponse.error()],
    ['a body the mapper rejects', () => HttpResponse.json({ revision: 1 })],
  ])('settle on bundled after %s, without retrying', async (_label, reply) => {
    const requests = recordRequests((request) => request.url.endsWith('/api/content/installation'));
    server.use(http.get('*/api/content/installation', reply));

    renderWithProviders(<Public />);

    expect(await screen.findByText('bundled')).toBeInTheDocument();
    expect(requests).toHaveLength(1);
  });

  it('read guest content for a session and language', async () => {
    renderWithProviders(<Guest sessionId="A1B2C3D4" language="en" />);

    expect(await screen.findByText('provided true')).toBeInTheDocument();
  });

  it('read unprovided guest content as content, not as a failure', async () => {
    renderWithProviders(<Guest sessionId="A1B2C3D4" language="ar" />);

    expect(await screen.findByText('provided false')).toBeInTheDocument();
  });

  it('ask nothing and count as settled before the language is known', () => {
    const requests = recordRequests((request) => request.url.includes('/content/'));

    renderWithProviders(<Guest sessionId="A1B2C3D4" />);

    expect(screen.getByText('bundled')).toBeInTheDocument();
    expect(requests).toEqual([]);
  });

  it('read staff content', async () => {
    renderWithProviders(<Staff />);

    expect(await screen.findByText('Europe/Berlin')).toBeInTheDocument();
  });

  it('settle staff content on bundled while the login directory is down (503)', async () => {
    server.use(
      http.get('*/api/admin/content', () =>
        HttpResponse.json({ detail: 'Studio content is temporarily unavailable' }, { status: 503 })
      )
    );

    renderWithProviders(<Staff />);

    expect(await screen.findByText('bundled')).toBeInTheDocument();
  });
});
