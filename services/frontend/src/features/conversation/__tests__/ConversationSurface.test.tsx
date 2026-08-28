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
    bottom: 'calc(0px + 40px + 0px)',
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
});
