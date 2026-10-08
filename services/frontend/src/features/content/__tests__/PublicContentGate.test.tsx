import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useQueryClient } from '@tanstack/react-query';
import { afterEach, describe, expect, it } from 'vitest';
import { PublicContentGate } from '@/features/content/PublicContentGate';
import { usePublicContent } from '@/features/content/usePublicContent';
import { contentKeys } from '@/features/content/contentQuery';
import { server } from '@/test/setup';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ContentSettled } from '@/test/ContentSettled';
import { installationBody } from '@/test/contentFixtures';

/** Records what installation content each of its renders saw. */
function Screen({ seen }: Readonly<{ seen: (string | undefined)[] }>) {
  const { content } = usePublicContent();
  seen.push(content?.locale);
  return <p>screen</p>;
}

/** Puts the installation query back to pending, as a cache reset would. */
function Reset() {
  const client = useQueryClient();
  return (
    <button
      type="button"
      onClick={() => void client.resetQueries({ queryKey: contentKeys.public })}
    >
      reset
    </button>
  );
}

function hold(): () => void {
  let release!: () => void;
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.get('*/api/content/installation', async () => {
      await released;
      return HttpResponse.json(installationBody);
    })
  );
  return release;
}

afterEach(() => {
  document.head.replaceChildren();
});

describe('PublicContentGate', () => {
  it('paints the app only once installation content has arrived, so nothing swaps', async () => {
    const seen: (string | undefined)[] = [];
    renderWithProviders(
      <PublicContentGate>
        <Screen seen={seen} />
      </PublicContentGate>,
      { publicContent: 'fetched' }
    );

    expect(screen.queryByText('screen')).not.toBeInTheDocument();
    // The themed page background, not the bare document, while it waits.
    expect(document.querySelector('[data-screen-shell]')).not.toBeNull();
    expect(await screen.findByText('screen')).toBeInTheDocument();
    expect(seen.length).toBeGreaterThan(0);
    expect(seen).not.toContain(undefined);
  });

  it('paints bundled copy at once when the content route fails', async () => {
    server.use(
      http.get('*/api/content/installation', () =>
        HttpResponse.json({ detail: 'unavailable' }, { status: 503 })
      )
    );

    renderWithProviders(
      <PublicContentGate waitMs={60_000}>
        <p>screen</p>
      </PublicContentGate>,
      { publicContent: 'fetched' }
    );

    expect(await screen.findByText('screen')).toBeInTheDocument();
  });

  it('stops waiting after the bound and takes the content when it lands', async () => {
    const release = hold();
    const seen: (string | undefined)[] = [];
    renderWithProviders(
      <>
        <PublicContentGate waitMs={20}>
          <Screen seen={seen} />
        </PublicContentGate>
        <ContentSettled />
      </>,
      { publicContent: 'fetched' }
    );

    expect(await screen.findByText('screen')).toBeInTheDocument();
    expect(seen).toEqual([undefined]);

    release();
    await screen.findByTestId('public-content-settled');
    await waitFor(() => expect(seen.at(-1)).toBe('de-DE'));
  });

  it('applies the installation icon as the favicon', async () => {
    const link = document.createElement('link');
    link.rel = 'icon';
    link.setAttribute('href', '/favicon-32x32.png');
    document.head.append(link);

    renderWithProviders(
      <PublicContentGate>
        <p>screen</p>
      </PublicContentGate>,
      { publicContent: 'fetched' }
    );

    await screen.findByText('screen');
    expect(link.getAttribute('href')).toBe(installationBody.branding.icon.url);
  });

  it('stays open once it has opened, even while the content is fetched again', async () => {
    renderWithProviders(
      <>
        <PublicContentGate>
          <Reset />
        </PublicContentGate>
        <ContentSettled />
      </>,
      { publicContent: 'fetched' }
    );
    const reset = await screen.findByRole('button', { name: 'reset' });

    const release = hold();
    await userEvent.click(reset);

    expect(screen.getByRole('button', { name: 'reset' })).toBeInTheDocument();
    release();
    await screen.findByTestId('public-content-settled');
  });
});
