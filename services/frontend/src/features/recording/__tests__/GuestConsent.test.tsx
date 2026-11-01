import { createHash } from 'node:crypto';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ClipLoader } from '@/core/audio/clips';
import { WAVE_HEIGHTS } from '@/core/audio/waveform';
import { ConversationScreen } from '@/features/conversation/ConversationScreen';
import { createFakeAudioPlayer } from '@/test/fakeAudioPlayer';
import { renderWithProviders } from '@/test/renderWithProviders';
import { createRealtimeWire } from '@/test/realtimeWire';
import { server } from '@/test/setup';

const SESSION = 'A1B2C3D4';
const HTML = '<p>The staff member would like to record this conversation.</p>';
const sha256 = (text: string) => createHash('sha256').update(text, 'utf8').digest('hex');
const arming = {
  state: 'arming',
  reason: null,
  window_id: 'w1',
  state_version: 2,
  since: new Date().toISOString(),
};

interface Served {
  consent_kind?: 'first' | 'resume';
  language?: string;
  documentation_consent?: { accept_label: string; decline_label: string };
  accept_label?: string;
  decline_label?: string;
  text_sha256?: string;
  html?: string;
  signature?: 'off' | 'optional' | 'required';
  proposed_name?: string | null;
}

/** Serves the text and records every answer; `refuse` answers the first yes with a code. */
function gateway(served: Served = {}, refuse?: string) {
  const answers: Record<string, unknown>[] = [];
  const reads = vi.fn();
  server.use(
    http.get(`*/api/customer/session/${SESSION}/recording/consent`, () => {
      reads();
      return HttpResponse.json({
        request_id: 'r-1',
        consent_kind: 'first',
        language: 'en',
        html: HTML,
        signature: 'off',
        proposed_name: null,
        ...served,
      });
    }),
    http.post(`*/api/customer/session/${SESSION}/recording/answer`, async ({ request }) => {
      answers.push((await request.json()) as Record<string, unknown>);
      if (refuse !== undefined && answers.length === 1) {
        return HttpResponse.json({ detail: { error_code: refuse, message: 'x' } }, { status: 409 });
      }
      return HttpResponse.json(arming);
    })
  );
  return { answers, reads };
}

async function ask(options: { clips?: ClipLoader; kind?: 'first' | 'resume' } = {}) {
  const wire = createRealtimeWire();
  const player = createFakeAudioPlayer();
  renderWithProviders(
    <Routes>
      <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
    </Routes>,
    {
      route: `/s/${SESSION}/live`,
      player: player.port,
      clips: options.clips,
      services: {
        message: {
          getHistory: vi.fn().mockResolvedValue([]),
          sendText: vi.fn(),
          sendAudio: vi.fn(),
          resolveAudioUrl: (url: string) => url,
        },
        createRealtime: () => wire.transport,
      },
    }
  );
  await screen.findByRole('button', { name: 'Record' });
  await wire.receive({
    ...arming,
    type: 'recording_state',
    role: 'recording_state',
    session_id: SESSION,
    state: 'asking',
    state_version: 1,
  });
  await wire.receive({
    type: 'recording_request',
    role: 'recording_request',
    session_id: SESSION,
    request_id: 'r-1',
    consent_kind: options.kind ?? 'first',
  });
  const dialog = await screen.findByRole('dialog');
  await within(dialog).findByText('The staff member would like to record this conversation.');
  return { dialog, player, wire };
}

/** jsdom has no canvas: a pen that records, and a PNG export. */
function mockCanvas() {
  const pen = {
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fillRect: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    pen as unknown as CanvasRenderingContext2D
  );
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
    'data:image/png;base64,iVBORw0K'
  );
  HTMLCanvasElement.prototype.setPointerCapture = vi.fn();
  return pen;
}

const yes = () => userEvent.click(screen.getByRole('button', { name: 'Yes, record' }));

afterEach(() => {
  vi.restoreAllMocks();
});

describe('the consent question, as the guest answers it', () => {
  it('shows served choices and explicitly identifies source-language wording', async () => {
    const { answers } = gateway({
      language: 'de',
      accept_label: 'Abschnitt freigeben',
      decline_label: 'Ablehnen',
      consent_kind: 'resume',
    });
    const { dialog } = await ask({ kind: 'resume' });
    expect(within(dialog).getByText(/Original.*de/)).toBeInTheDocument();
    const yes = within(dialog).getByRole('button', { name: 'Abschnitt freigeben' });
    expect(yes).toHaveAttribute('lang', 'de');
    expect(
      within(dialog)
        .getByText('The staff member would like to record this conversation.')
        .closest('[lang]')
    ).toHaveAttribute('lang', 'de');
    await userEvent.click(yes);
    await vi.waitFor(() => expect(answers[0]).toMatchObject({ text_sha256: sha256(HTML) }));
  });

  it('requires documentation consent separately before the renewed section release', async () => {
    const { answers } = gateway({
      consent_kind: 'resume',
      accept_label: 'Release this section',
      decline_label: 'Decline section',
      documentation_consent: {
        accept_label: 'I consent to documentation',
        decline_label: 'I decline documentation',
      },
    });
    const { dialog } = await ask({ kind: 'resume' });
    const release = within(dialog).getByRole('button', { name: 'Release this section' });
    expect(release).toBeDisabled();
    await userEvent.click(
      within(dialog).getByRole('checkbox', { name: 'I consent to documentation' })
    );
    expect(release).toBeEnabled();
    await userEvent.click(release);
    await vi.waitFor(() =>
      expect(answers[0]).toMatchObject({ consent: true, documentation_consent: true })
    );
  });

  it.each([
    ['DOCUMENTATION_CONSENT_REQUIRED', 'Please confirm the documentation consent separately.'],
    [
      'STAFF_RELEASE_TEXT_MISMATCH',
      'The employee release has changed. Please ask the staff member to withdraw this request and send a new one.',
    ],
  ])('explains a refused legal confirmation: %s', async (code, message) => {
    gateway({ consent_kind: 'resume' }, code);
    const { dialog } = await ask({ kind: 'resume' });
    await yes();
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(message);
  });

  it('uses the served version digest for the answer and read-aloud clip', async () => {
    const digest = 'b'.repeat(64);
    const { answers } = gateway({ consent_kind: 'resume', text_sha256: digest });
    const { dialog, player } = await ask({ kind: 'resume' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Read aloud' }));
    await vi.waitFor(() => expect(player.played[0]).toContain(`text_sha256=${digest}`));
    await yes();
    await vi.waitFor(() => expect(answers[0]).toMatchObject({ text_sha256: digest }));
  });

  it('reads the text again and says why when the text changed under the guest', async () => {
    const { answers, reads } = gateway({}, 'CONSENT_TEXT_MISMATCH');
    const { dialog } = await ask();
    await userEvent.type(within(dialog).getByLabelText('Your name'), 'Amira');

    await yes();

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'The text has changed. Please read it again before you answer.'
    );
    expect(answers).toHaveLength(1);
    await vi.waitFor(() => expect(reads).toHaveBeenCalledTimes(2));
  });

  it('confirms the name the employee typed, and says who typed it', async () => {
    const { answers } = gateway({ proposed_name: 'Amira Haddad' });
    const { dialog } = await ask();

    expect(within(dialog).getByLabelText('Your name')).toHaveValue('Amira Haddad');
    expect(dialog).toHaveTextContent('Entered by the staff member. Please check it.');
    await yes();

    await vi.waitFor(() => expect(answers[0]).toMatchObject({ name: 'Amira Haddad' }));
  });

  it('holds a yes without a name or a required signature, and offers the tap instead', async () => {
    const { answers } = gateway({ signature: 'required' });
    const { dialog } = await ask();

    await yes();
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Please enter your name.');
    await userEvent.type(within(dialog).getByLabelText('Your name'), 'Amira');
    await yes();
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Please sign, or confirm that you cannot sign.'
    );
    expect(answers).toHaveLength(0);

    await userEvent.click(within(dialog).getByText('I cannot sign and confirm by tapping.'));
    await yes();

    await vi.waitFor(() =>
      expect(answers[0]).toEqual({
        request_id: 'r-1',
        consent: true,
        text_sha256: sha256(HTML),
        name: 'Amira',
        cannot_sign: true,
      })
    );
  });

  it('sends a drawn signature as a PNG', async () => {
    const pen = mockCanvas();
    HTMLCanvasElement.prototype.setPointerCapture = vi.fn();
    const { answers } = gateway({ signature: 'optional' });
    const { dialog } = await ask();
    await userEvent.type(within(dialog).getByLabelText('Your name'), 'Amira');

    const pad = within(dialog).getByLabelText('Your signature (optional)');
    await userEvent.pointer([
      { keys: '[MouseLeft>]', target: pad, coords: { clientX: 5, clientY: 5 } },
      { target: pad, coords: { clientX: 20, clientY: 15 } },
      { keys: '[/MouseLeft]', target: pad },
    ]);
    await yes();

    await vi.waitFor(() => expect(answers[0]).toMatchObject({ signature_png: 'iVBORw0K' }));
    expect(pen.lineTo).toHaveBeenCalled();
  });

  it('counts a tap on the pad as no signature', async () => {
    mockCanvas();
    const { answers } = gateway({ signature: 'required' });
    const { dialog } = await ask();
    await userEvent.type(within(dialog).getByLabelText('Your name'), 'Amira');

    const pad = within(dialog).getByLabelText('Your signature');
    await userEvent.pointer([
      { keys: '[MouseLeft>]', target: pad, coords: { clientX: 5, clientY: 5 } },
      { keys: '[/MouseLeft]', target: pad },
    ]);
    await yes();

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Please sign, or confirm that you cannot sign.'
    );
    expect(answers).toHaveLength(0);
  });

  it('asks for the signature again when the gateway could not read it', async () => {
    gateway({ signature: 'optional' }, 'INVALID_SIGNATURE');
    const { dialog } = await ask();
    await userEvent.type(within(dialog).getByLabelText('Your name'), 'Amira');

    await yes();

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Please sign, or confirm that you cannot sign.'
    );
  });

  it("offers no remembered names and keeps to the gateway's length", async () => {
    gateway();
    const { dialog } = await ask();
    const name = within(dialog).getByLabelText('Your name');
    expect(name).toHaveAttribute('autocomplete', 'off');
    expect(name).toHaveAttribute('maxlength', '200');
  });

  it('holds the yes while a changed text is read again', async () => {
    let reads = 0;
    let release = () => {};
    gateway({}, 'CONSENT_TEXT_MISMATCH');
    server.use(
      http.get(`*/api/customer/session/${SESSION}/recording/consent`, async () => {
        reads += 1;
        if (reads > 1) await new Promise<void>((resolve) => (release = resolve));
        return HttpResponse.json({
          request_id: 'r-1',
          consent_kind: 'first',
          language: 'en',
          html: reads > 1 ? '<p>New text</p>' : HTML,
          signature: 'off',
          proposed_name: null,
        });
      })
    );
    const { dialog } = await ask();
    await userEvent.type(within(dialog).getByLabelText('Your name'), 'Amira');

    await yes();

    expect(await within(dialog).findByText('Loading the text…')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Yes, record' })).toBeDisabled();
    release();
    expect(await within(dialog).findByText('New text')).toBeInTheDocument();
  });

  it('answers a resume with the text alone', async () => {
    const { answers } = gateway({ consent_kind: 'resume', signature: 'off' });
    const { dialog } = await ask({ kind: 'resume' });

    expect(within(dialog).queryByLabelText('Your name')).toBeNull();
    await yes();

    await vi.waitFor(() =>
      expect(answers[0]).toEqual({ request_id: 'r-1', consent: true, text_sha256: sha256(HTML) })
    );
  });

  it('reads the text aloud through the conversation player, and stops', async () => {
    gateway();
    const { dialog, player } = await ask();

    await userEvent.click(within(dialog).getByRole('button', { name: 'Read aloud' }));

    await vi.waitFor(() =>
      expect(player.played).toEqual([
        `/api/customer/session/${SESSION}/recording/consent/audio?request_id=r-1&text_sha256=${sha256(HTML)}`,
      ])
    );
    await player.started();
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Stop reading' }));
    expect(player.stop).toHaveBeenCalled();
    expect(await within(dialog).findByRole('button', { name: 'Read aloud' })).toBeInTheDocument();
    expect(player.played).toHaveLength(1);
  });

  it('stops reading once the question closes', async () => {
    gateway();
    const { dialog, player, wire } = await ask();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Read aloud' }));
    await vi.waitFor(() => expect(player.played).toHaveLength(1));
    await player.started();
    player.stop.mockClear();

    await wire.receive({
      ...arming,
      type: 'recording_state',
      role: 'recording_state',
      session_id: SESSION,
    });

    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(player.stop).toHaveBeenCalled();
  });

  it('hides reading aloud when the language has no voice', async () => {
    gateway();
    const clips: ClipLoader = {
      load: (url) =>
        url.includes('/consent/audio')
          ? Promise.reject(new Error('503'))
          : Promise.resolve({ objectUrl: url, peaks: WAVE_HEIGHTS }),
      peek: () => null,
      dispose: () => undefined,
    };
    const { dialog } = await ask({ clips });

    await userEvent.click(within(dialog).getByRole('button', { name: 'Read aloud' }));

    await vi.waitFor(() =>
      expect(within(dialog).queryByRole('button', { name: 'Read aloud' })).toBeNull()
    );
  });

  it('cannot say yes to a text it could not load', async () => {
    server.use(
      http.get(`*/api/customer/session/${SESSION}/recording/consent`, () =>
        HttpResponse.json(
          { detail: { error_code: 'RECORDING_POLICY_UNAVAILABLE' } },
          { status: 503 }
        )
      )
    );
    const wire = createRealtimeWire();
    renderWithProviders(
      <Routes>
        <Route path="/s/:sessionId/live" element={<ConversationScreen />} />
      </Routes>,
      { route: `/s/${SESSION}/live`, services: { createRealtime: () => wire.transport } }
    );
    await screen.findByRole('button', { name: 'Record' });
    await wire.receive({
      type: 'recording_request',
      role: 'recording_request',
      session_id: SESSION,
      request_id: 'r-1',
      consent_kind: 'first',
    });
    await wire.receive({
      ...arming,
      type: 'recording_state',
      role: 'recording_state',
      session_id: SESSION,
      state: 'asking',
      state_version: 1,
    });

    const dialog = await screen.findByRole('dialog');
    expect(
      await within(dialog).findByText(
        'The text cannot be loaded right now. Please ask the staff member.'
      )
    ).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Yes, record' })).toBeDisabled();
  });
});
