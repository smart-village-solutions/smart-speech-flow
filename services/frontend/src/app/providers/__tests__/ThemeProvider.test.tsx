import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from '@/app/providers/ThemeProvider';
import { useTheme } from '@/app/providers/theme';

function Probe() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button type="button" onClick={toggleTheme}>
      {theme}
    </button>
  );
}

function mediaQueryList(matches: boolean): MediaQueryList {
  return {
    matches,
    media: '(prefers-color-scheme: dark)',
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
    addListener: () => {},
    removeListener: () => {},
  } as MediaQueryList;
}

afterEach(() => {
  document.documentElement.className = '';
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('ThemeProvider', () => {
  it('uses light when no saved choice exists and the system prefers light', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQueryList(false));

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>
    );

    expect(screen.getByRole('button')).toHaveTextContent('light');
    expect(document.documentElement).not.toHaveClass('dark');
  });

  it('uses dark when no saved choice exists and the system prefers dark', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQueryList(true));

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>
    );

    expect(screen.getByRole('button')).toHaveTextContent('dark');
    expect(document.documentElement).toHaveClass('dark');
  });

  it('follows a system preference change until a manual choice is saved', () => {
    const listeners = new Set<(event: MediaQueryListEvent) => void>();
    const mediaQuery = {
      matches: false,
      addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
        listeners.add(listener as (event: MediaQueryListEvent) => void);
      },
      removeEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
        listeners.delete(listener as (event: MediaQueryListEvent) => void);
      },
    } as MediaQueryList;
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQuery);

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>
    );

    expect(screen.getByRole('button')).toHaveTextContent('light');

    act(() => {
      listeners.forEach((listener) => listener({ matches: true } as MediaQueryListEvent));
    });

    expect(screen.getByRole('button')).toHaveTextContent('dark');
    expect(document.documentElement).toHaveClass('dark');
  });

  it('persists a manual choice over the system preference', async () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQueryList(false));

    const { unmount } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>
    );

    await userEvent.click(screen.getByRole('button'));

    expect(screen.getByRole('button')).toHaveTextContent('dark');
    expect(localStorage.getItem('ssf-theme')).toBe('dark');

    unmount();
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>
    );

    expect(screen.getByRole('button')).toHaveTextContent('dark');
  });
});
