import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { createFakeAudioPlayer } from '@/test/fakeAudioPlayer';
import { createFakeClipLoader, stripedPeaks } from '@/test/fakeClipLoader';
import { renderWithProviders } from '@/test/renderWithProviders';
import { MessageBubble } from '@/ui/patterns/MessageBubble';
import type { ChatMessage } from '@/domain/message/message.types';
import { BAR_COUNT } from '@/core/audio/waveform';

const own: ChatMessage = {
  id: 'm1',
  origin: 'self',
  text: 'I need a passport',
  audioUrl: null,
  sourceLanguage: 'en',
  targetLanguage: 'de',
  timestamp: '2026-08-21T10:00:00+00:00',
  state: 'sent',
};

const incoming: ChatMessage = {
  ...own,
  id: 'm2',
  origin: 'peer',
  text: 'Do you have your old passport?',
  audioUrl: '/api/audio/m2.wav',
};

describe('MessageBubble', () => {
  it('renders an own message with the self corner and no player', () => {
    const { container } = renderWithProviders(<MessageBubble message={own} />);

    expect(screen.getByText('I need a passport')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Play' })).not.toBeInTheDocument();
    expect(container.querySelector('.rounded-bubble-self')).not.toBeNull();
  });

  it('renders an incoming message with the peer corner and a player', () => {
    const { container } = renderWithProviders(<MessageBubble message={incoming} />);

    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument();
    expect(container.querySelector('.rounded-bubble-peer')).not.toBeNull();
  });

  it('renders typing dots instead of text while a message is pending', () => {
    renderWithProviders(<MessageBubble message={{ ...own, text: '', state: 'pending' }} />);

    expect(screen.getByTestId('typing-dots')).toBeInTheDocument();
  });

  // A failed send stops being pending, so without its own branch the bubble
  // rendered the placeholder's empty text: a blank card with no explanation.
  it('shows the words that failed to send', () => {
    renderWithProviders(
      <MessageBubble message={{ ...own, text: 'I need a passport', state: 'failed' }} />
    );

    expect(screen.getByText('I need a passport')).toBeInTheDocument();
    expect(screen.getByTestId('failed-message')).toBeInTheDocument();
  });

  it('names a failed recording, which never had a transcript', () => {
    renderWithProviders(<MessageBubble message={{ ...own, text: '', state: 'failed' }} />);

    expect(screen.getByText('Not sent')).toBeInTheDocument();
  });

  it('sizes a pending bubble to its content and a settled one to the stack', () => {
    const { container: pendingTree } = renderWithProviders(
      <MessageBubble message={{ ...own, text: '', state: 'pending' }} />
    );
    expect(pendingTree.querySelector('.rounded-bubble-self')).toHaveClass('w-fit');

    const { container: sentTree } = renderWithProviders(<MessageBubble message={own} />);
    expect(sentTree.querySelector('.rounded-bubble-self')).not.toHaveClass('w-fit');
  });

  it('gives each side exactly one inline margin per edge', () => {
    const { container: ownTree } = renderWithProviders(<MessageBubble message={own} />);
    const ownBubble = ownTree.querySelector('.rounded-bubble-self');
    expect(ownBubble).toHaveClass('ms-bubble-inset', 'me-bubble-gutter');
    expect(ownBubble).not.toHaveClass('ms-bubble-gutter');
    expect(ownBubble).not.toHaveClass('me-bubble-inset');

    const { container: peerTree } = renderWithProviders(<MessageBubble message={incoming} />);
    const peerBubble = peerTree.querySelector('.rounded-bubble-peer');
    expect(peerBubble).toHaveClass('ms-bubble-gutter', 'me-bubble-inset');
    expect(peerBubble).not.toHaveClass('ms-bubble-inset');
    expect(peerBubble).not.toHaveClass('me-bubble-gutter');
  });

  it('omits the player for an incoming message with no audio', () => {
    renderWithProviders(<MessageBubble message={{ ...incoming, audioUrl: null }} />);

    expect(screen.queryByRole('button', { name: 'Play' })).not.toBeInTheDocument();
  });

  it('turns into a pause button while its own clip is playing', async () => {
    const player = createFakeAudioPlayer();
    const { container } = renderWithProviders(<MessageBubble message={incoming} />, {
      player: player.port,
    });

    expect(container.querySelector('[data-icon="play"]')).not.toBeNull();

    await userEvent.click(screen.getByRole('button', { name: 'Play' }));
    await player.started();

    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument();
    expect(container.querySelector('[data-icon="pause"]')).not.toBeNull();

    await player.end();

    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument();
    expect(container.querySelector('[data-icon="play"]')).not.toBeNull();
  });

  it('pauses where it stands and resumes from there, rather than restarting', async () => {
    const player = createFakeAudioPlayer();
    renderWithProviders(<MessageBubble message={incoming} />, { player: player.port });

    await userEvent.click(screen.getByRole('button', { name: 'Play' }));
    await player.started();
    await player.progress(0.5);

    await userEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(player.paused).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Play' }));
    expect(player.resumed).toHaveBeenCalledTimes(1);
    // A resume is not a fresh play: the clip was never loaded a second time.
    expect(player.played).toEqual(['/api/audio/m2.wav']);
  });

  it('keeps the waveform where it was paused', async () => {
    const player = createFakeAudioPlayer();
    const { container } = renderWithProviders(<MessageBubble message={incoming} />, {
      player: player.port,
    });

    await userEvent.click(screen.getByRole('button', { name: 'Play' }));
    await player.started();
    await player.progress(0.5);
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }));

    expect(container.querySelectorAll('.bg-accent').length).toBe(BAR_COUNT / 2);
  });

  it('starts a fresh clip rather than resuming when a different bubble is playing', async () => {
    const player = createFakeAudioPlayer();
    renderWithProviders(
      <>
        <MessageBubble message={incoming} />
        <MessageBubble message={{ ...incoming, id: 'm3', audioUrl: '/api/audio/m3.wav' }} />
      </>,
      { player: player.port }
    );

    const [first, second] = screen.getAllByRole('button', { name: 'Play' });
    await userEvent.click(first);
    await player.started();
    await userEvent.click(second as HTMLElement);

    expect(player.played).toEqual(['/api/audio/m2.wav', '/api/audio/m3.wav']);
  });

  it('fills the waveform in step with playback progress', async () => {
    const player = createFakeAudioPlayer();
    const { container } = renderWithProviders(<MessageBubble message={incoming} />, {
      player: player.port,
    });

    const filled = () => container.querySelectorAll('.bg-accent').length;
    expect(filled()).toBe(0);

    await userEvent.click(screen.getByRole('button', { name: 'Play' }));
    await player.started();
    await player.progress(0.5);

    expect(filled()).toBe(BAR_COUNT / 2);

    // A clip heard to the end leaves a solid waveform rather than emptying:
    // the export stops its animation on the last bar and keeps the count.
    await player.end();

    expect(filled()).toBe(BAR_COUNT);
  });

  it('shows no waveform at all until its clip has been played', () => {
    const { container } = renderWithProviders(<MessageBubble message={incoming} />);

    // There is no idle track behind the bars, so an unheard message draws an
    // empty row — every slot holds its width and none of them is painted.
    expect(container.querySelectorAll('.bg-accent')).toHaveLength(0);
    const slots = container.querySelectorAll('[aria-hidden="true"] > div');
    expect(slots).toHaveLength(BAR_COUNT);
    expect([...slots].every((slot) => slot.className.includes('bg-surface-wave-idle'))).toBe(true);
  });

  it('empties the waveform again when a clip is cut short rather than ended', async () => {
    const player = createFakeAudioPlayer();
    const { container } = renderWithProviders(
      <>
        <MessageBubble message={incoming} />
        <MessageBubble message={{ ...incoming, id: 'm3', audioUrl: '/api/audio/m3.wav' }} />
      </>,
      { player: player.port }
    );

    const [first, second] = screen.getAllByRole('button', { name: 'Play' });
    await userEvent.click(first);
    await player.started();
    await player.progress(0.5);

    // Interrupted at the half way mark, so it was never heard in full.
    await userEvent.click(second as HTMLElement);
    await player.started();

    expect(container.querySelectorAll('.bg-accent')).toHaveLength(0);
  });

  it('leaves its waveform empty while a different bubble is the one playing', async () => {
    const player = createFakeAudioPlayer();
    const { container } = renderWithProviders(
      <>
        <MessageBubble message={incoming} />
        <MessageBubble message={{ ...incoming, id: 'm3', audioUrl: '/api/audio/m3.wav' }} />
      </>,
      { player: player.port }
    );

    const [first, second] = screen.getAllByRole('button', { name: 'Play' });
    expect(second).toBeDefined();

    await userEvent.click(first);
    await player.started();
    await player.progress(1);

    // Every filled bar belongs to the bubble that is actually playing.
    expect(container.querySelectorAll('.bg-accent').length).toBe(BAR_COUNT);
  });

  it('draws the real shape of the clip once it has been decoded', async () => {
    const clips = createFakeClipLoader();
    clips.provide('/api/audio/m2.wav', stripedPeaks());

    const { container } = renderWithProviders(<MessageBubble message={incoming} />, { clips });

    await waitFor(() => {
      const bars = [...container.querySelectorAll<HTMLElement>('[aria-hidden="true"] > div')];
      expect(bars[0].style.height).toBe('100%');
      expect(bars[1].style.height).toBe('10%');
    });

    expect(clips.loaded).toEqual(['/api/audio/m2.wav']);
  });

  it('keeps the decorative shape when the clip cannot be decoded', async () => {
    const clips = createFakeClipLoader();

    const { container } = renderWithProviders(<MessageBubble message={incoming} />, { clips });

    await waitFor(() => expect(clips.loaded).toEqual(['/api/audio/m2.wav']));

    const bars = [...container.querySelectorAll<HTMLElement>('[aria-hidden="true"] > div')];
    expect(bars[0].style.height).toBe('4px');
  });

  it('asks for no clip when the message carries no audio', () => {
    const clips = createFakeClipLoader();

    renderWithProviders(<MessageBubble message={own} />, { clips });

    expect(clips.loaded).toEqual([]);
  });

  // Measured in Chrome: with the bubble sized by `self-end` shrink-to-fit, the
  // 50 flex-1 bars contribute nothing to its intrinsic width, so the row was
  // just its 49 gaps and every bar came out 0.00px wide. Only bubbles whose
  // text happened to be longer than the row showed a waveform at all, which is
  // why bar width differed from bubble to bubble.
  it('gives an audio bubble a definite width, so its bars cannot collapse', () => {
    const { container: audioTree } = renderWithProviders(<MessageBubble message={incoming} />);
    expect(audioTree.querySelector('.rounded-bubble-peer')).toHaveClass('w-bubble-span');

    // A peer bubble with nothing to play still hugs its text.
    const { container: textTree } = renderWithProviders(
      <MessageBubble message={{ ...incoming, audioUrl: null }} />
    );
    expect(textTree.querySelector('.rounded-bubble-peer')).toHaveClass('self-end');
    expect(textTree.querySelector('.rounded-bubble-peer')).not.toHaveClass('w-bubble-span');
  });
});
