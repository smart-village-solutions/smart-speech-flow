import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ConversationSurface } from '@/features/conversation/ConversationSurface';
import type { ConversationScreenState } from '@/features/conversation/useConversationScreen';

const state = (): ConversationScreenState =>
  ({
    state: {
      messages: [],
      composer: 'idle',
      sending: false,
      connection: 'connected',
      hasConnected: true,
      ended: false,
      errorKey: null,
      canRetry: false,
    },
    recorder: {
      phase: 'idle',
      levels: [],
      elapsedSeconds: 0,
      start: () => undefined,
      stop: () => undefined,
    },
    retryLast: null,
    flight: null,
    chatRef: { current: null },
    composerRef: { current: null },
    sourceRef: { current: null },
    keyboardOffset: 0,
    // Opaque on purpose: jsdom folds a calc() of plain lengths into one length.
    legalBottom: 'var(--test-legal-bottom)',
    legalBand: 'var(--test-legal-band)',
    showsLegal: true,
    legalRef: { current: null },
    bottom: 'var(--test-buttons-bottom)',
    composerLift: '0px',
    draft: '',
    setDraft: () => undefined,
    isTyping: false,
    isRecording: false,
    canCompose: true,
    hasDraft: false,
    showsStatus: false,
    submitDraft: () => undefined,
    cancelDraft: () => undefined,
    toggleMic: () => undefined,
    toggleKeyboard: () => undefined,
    customerLanguage: 'ar',
  }) as unknown as ConversationScreenState;

describe('ConversationSurface', () => {
  it('renders the header it is given', () => {
    renderWithProviders(
      <ConversationSurface screen={state()} header={<h1>A header</h1>} contentTop="72px" />
    );
    expect(screen.getByRole('heading', { name: 'A header' })).toBeInTheDocument();
  });

  it('renders an overlay when one is given, and nothing when not', () => {
    const { unmount } = renderWithProviders(
      <ConversationSurface
        screen={state()}
        header={<h1>h</h1>}
        contentTop="72px"
        overlay={<p>An overlay</p>}
      />
    );
    expect(screen.getByText('An overlay')).toBeInTheDocument();
    unmount();

    renderWithProviders(
      <ConversationSurface screen={state()} header={<h1>h</h1>} contentTop="72px" />
    );
    expect(screen.queryByText('An overlay')).not.toBeInTheDocument();
  });

  it('renders a footer when one is given', () => {
    renderWithProviders(
      <ConversationSurface
        screen={state()}
        header={<h1>h</h1>}
        contentTop="72px"
        footer={<button type="button">End it</button>}
      />
    );
    expect(screen.getByRole('button', { name: 'End it' })).toBeInTheDocument();
  });

  it('starts the chat stack where it is told to', () => {
    const { container } = renderWithProviders(
      <ConversationSurface screen={state()} header={<h1>h</h1>} contentTop="128px" />
    );
    const stack = container.querySelector('[data-chat-stack]');
    expect(stack).toHaveStyle({ top: '128px' });
  });

  it('puts the legal links in their own row below the buttons row', () => {
    const { container } = renderWithProviders(
      <ConversationSurface screen={state()} header={<h1>h</h1>} contentTop="72px" />
    );

    const legal = screen.getByRole('navigation', { name: 'Legal information' });
    const row = legal.closest('[data-legal-row]');
    const buttons = container.querySelector('[data-dismiss-keep]');
    expect(row).not.toBeNull();
    expect(buttons).not.toBeNull();
    expect(buttons?.contains(legal)).toBe(false);
    expect(row).toHaveStyle({ bottom: 'var(--test-legal-bottom)' });
    expect(buttons).toHaveStyle({ bottom: 'var(--test-buttons-bottom)' });
  });

  it('measures the legal row and lets taps through its empty width to the buttons', () => {
    const screenState = state();
    renderWithProviders(
      <ConversationSurface screen={screenState} header={<h1>h</h1>} contentTop="72px" />
    );

    const row = screen
      .getByRole('navigation', { name: 'Legal information' })
      .closest('[data-legal-row]');
    expect(screenState.legalRef.current).toBe(row);
    expect(row).toHaveClass('pointer-events-none', '[&_a]:pointer-events-auto');
  });

  it('hides the legal row while the keyboard is open', () => {
    renderWithProviders(
      <ConversationSurface
        screen={{ ...state(), showsLegal: false }}
        header={<h1>h</h1>}
        contentTop="72px"
      />
    );

    expect(screen.queryByRole('navigation', { name: 'Legal information' })).not.toBeInTheDocument();
  });

  it('gives the chat stack up to the legal band', () => {
    const { container } = renderWithProviders(
      <ConversationSurface screen={state()} header={<h1>h</h1>} contentTop="72px" />
    );

    expect(container.querySelector('[data-chat-stack]')?.getAttribute('style')).toContain(
      'var(--test-legal-band)'
    );
  });
});
