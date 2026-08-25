import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';

function setup(sendText = vi.fn()) {
  renderWithProviders(
    <Routes>
      <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
    </Routes>,
    {
      route: '/s/A1B2C3D4/live',
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText,
          sendAudio: vi.fn(),
          audioUrlFor: (id: string) => `/api/audio/${id}.wav`,
        },
      },
    }
  );
}

const composer = () => screen.queryByPlaceholderText('Type your message…');

async function openKeyboard() {
  await userEvent.click(await screen.findByRole('button', { name: 'Open keyboard' }));
}

describe('ConversationScreen composer dismissal', () => {
  it('closes the composer and frees the mic when the tap lands outside', async () => {
    setup();
    await openKeyboard();
    expect(composer()).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Record' })).toBeDisabled();

    await userEvent.click(document.body);

    expect(composer()).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Record' })).toBeEnabled();
  });

  it('keeps the draft, so reopening the keyboard restores it', async () => {
    setup();
    await openKeyboard();
    await userEvent.type(screen.getByPlaceholderText('Type your message…'), 'half a thought');

    await userEvent.click(document.body);
    await openKeyboard();

    expect(composer()).toHaveValue('half a thought');
  });

  it('stays open when the tap lands on the composer itself', async () => {
    setup();
    await openKeyboard();

    await userEvent.click(screen.getByPlaceholderText('Type your message…'));

    expect(composer()).toBeInTheDocument();
  });

  it('still sends when the tap lands on the send button', async () => {
    const sendText = vi.fn().mockResolvedValue({
      messageId: 'm5',
      originalText: 'hello',
      translatedText: 'hallo',
      audioUrl: null,
      processingTimeMs: 100,
    });
    setup(sendText);
    await openKeyboard();
    await userEvent.type(screen.getByPlaceholderText('Type your message…'), 'hello');

    await userEvent.click(screen.getByRole('button', { name: 'Send text' }));

    expect(sendText).toHaveBeenCalledWith('A1B2C3D4', expect.objectContaining({ text: 'hello' }));
  });
});
