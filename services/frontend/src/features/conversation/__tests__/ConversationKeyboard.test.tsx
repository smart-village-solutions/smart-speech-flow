import { act, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';

/** jsdom has no visualViewport; this one shrinks like a phone's when its keyboard opens. */
function fakeVisualViewport() {
  const listeners = new Set<() => void>();
  let keyboard = 0;
  const viewport = {
    get height() {
      return window.innerHeight - keyboard;
    },
    offsetTop: 0,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  };
  vi.stubGlobal('visualViewport', viewport);
  return {
    open(px: number) {
      keyboard = px;
      listeners.forEach((listener) => listener());
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the conversation with the on-screen keyboard', () => {
  it('compacts the header while the keyboard is open, and restores it after', async () => {
    const keyboard = fakeVisualViewport();
    renderWithProviders(
      <Routes>
        <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
      </Routes>,
      { route: '/s/A1B2C3D4/live' }
    );
    await screen.findByRole('button', { name: 'Record' });
    const shell = () => document.querySelector('[data-screen-shell]');

    expect(shell()).not.toHaveAttribute('data-keyboard');

    await act(async () => keyboard.open(300));
    expect(shell()).toHaveAttribute('data-keyboard', 'open');

    await act(async () => keyboard.open(0));
    expect(shell()).not.toHaveAttribute('data-keyboard');
  });
});
