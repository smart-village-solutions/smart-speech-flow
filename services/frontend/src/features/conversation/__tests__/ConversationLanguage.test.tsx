import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import type { RealtimeEvent, RealtimeTransport } from '@/core/realtime/realtime.port';
import { AppError } from '@/core/http/AppError';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';

const route = '/s/A1B2C3D4/live';

function tree() {
  return (
    <Routes>
      <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
    </Routes>
  );
}

function fakeTransport() {
  const handlers: ((event: RealtimeEvent) => void)[] = [];
  const transport: RealtimeTransport = {
    connect: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn(),
    send: vi.fn(),
    onEvent: (handler) => {
      handlers.push(handler);
      return () => handlers.splice(handlers.indexOf(handler), 1);
    },
    onStatus: () => () => undefined,
    getStatus: () => 'connected',
  };
  return {
    transport,
    async receive(event: RealtimeEvent) {
      await act(async () => {
        handlers.forEach((handler) => handler(event));
      });
    },
  };
}

/** The session as the gateway reports it, in whichever language it holds now. */
function serveSession(language: { current: string }, reads: { count: number }) {
  server.use(
    http.get('*/api/customer/session/A1B2C3D4', () => {
      reads.count += 1;
      return HttpResponse.json({
        session_id: 'A1B2C3D4',
        status: 'active',
        customer_language: language.current,
        admin_connected: true,
        customer_connected: true,
        created_at: '2026-10-12T10:00:00+00:00',
      });
    })
  );
}

describe('the conversation follows the guest language', () => {
  it('re-reads the session when the gateway says the guest language changed', async () => {
    const language = { current: 'en' };
    const reads = { count: 0 };
    serveSession(language, reads);
    const wire = fakeTransport();

    renderWithProviders(tree(), {
      route,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText: vi.fn(),
          sendAudio: vi.fn(),
          resolveAudioUrl: (url: string) => url,
        },
        createRealtime: () => wire.transport,
      },
    });
    await screen.findByRole('button', { name: 'Record' });
    await waitFor(() => expect(reads.count).toBe(1));

    language.current = 'tr';
    await wire.receive({
      role: 'customer_language_changed',
      type: 'customer_language_changed',
      customer_language: 'tr',
    });

    await waitFor(() => expect(reads.count).toBe(2));
  });

  it('retries a send refused for its language in the language the session holds now', async () => {
    const language = { current: 'en' };
    const reads = { count: 0 };
    serveSession(language, reads);
    const sendText = vi
      .fn()
      .mockImplementationOnce(() => {
        language.current = 'tr';
        return Promise.reject(new AppError('languageChanged', { status: 400 }));
      })
      .mockResolvedValueOnce({
        messageId: 'm2',
        originalText: 'hello',
        translatedText: 'merhaba',
        audioUrl: null,
      });

    renderWithProviders(tree(), {
      route,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText,
          sendAudio: vi.fn(),
          resolveAudioUrl: (url: string) => url,
        },
      },
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Open keyboard' }));
    await userEvent.type(screen.getByPlaceholderText('Type your message…'), 'hello');
    await userEvent.click(screen.getByRole('button', { name: 'Send text' }));
    // The refusal re-reads the session, which now holds Turkish; the screen follows it.
    await waitFor(() => expect(reads.count).toBe(2));

    await userEvent.click(await screen.findByRole('button', { name: 'Tekrar dene' }));

    await waitFor(() => expect(sendText).toHaveBeenCalledTimes(2));
    expect(sendText.mock.calls[0][1]).toMatchObject({ sourceLanguage: 'en' });
    expect(sendText.mock.calls[1][1]).toMatchObject({ sourceLanguage: 'tr' });
  });
});
