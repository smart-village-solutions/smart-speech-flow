import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppError } from '@/core/http/AppError';
import type { KeyConfirmationRepository } from '@/domain/recording/keyConfirmation.repository';
import { KeyConfirmationScreen } from '@/features/keys/KeyConfirmationScreen';
import { renderWithProviders } from '@/test/renderWithProviders';

const TOKEN = 'A'.repeat(43);
const display = '0505 0505 0505 0505 0505 0505 0505 0505 0505 0505';
const details = {
  fingerprintDisplay: display,
  requestedAt: '2026-11-02T09:30:00+00:00',
  expiresAt: '2026-11-02T10:00:00+00:00',
};

function refused(code: string) {
  return new AppError('validation', { status: 409, serverCode: code });
}

function render(overrides: Partial<KeyConfirmationRepository> = {}, hash = `#${TOKEN}`) {
  window.history.replaceState(null, '', `/key-confirmation${hash}`);
  const keyConfirmation: KeyConfirmationRepository = {
    lookup: vi.fn().mockResolvedValue(details),
    confirm: vi
      .fn()
      .mockResolvedValue({ fingerprint: new Uint8Array(32), fingerprintDisplay: display }),
    decline: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  renderWithProviders(<KeyConfirmationScreen />, {
    route: '/key-confirmation',
    locale: 'en',
    services: { keyConfirmation },
  });
  return keyConfirmation;
}

describe('KeyConfirmationScreen', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/');
  });

  it('reads the token once, clears it from the address bar and shows the key', async () => {
    const repo = render();
    expect(await screen.findByText(display)).toBeInTheDocument();
    expect(window.location.hash).toBe('');
    expect(repo.lookup).toHaveBeenCalledOnce();
    expect(repo.lookup).toHaveBeenCalledWith(TOKEN);
    expect(screen.getByRole('heading', { name: 'Confirm your new key' })).toBeInTheDocument();
  });

  it('confirms the key', async () => {
    const repo = render();
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm key' }));
    expect(await screen.findByText('Your new key is active.')).toBeInTheDocument();
    expect(repo.confirm).toHaveBeenCalledWith(TOKEN);
    expect(repo.decline).not.toHaveBeenCalled();
  });

  it("declines with This wasn't me", async () => {
    const repo = render();
    await userEvent.click(await screen.findByRole('button', { name: "This wasn't me" }));
    expect(await screen.findByText(/previous key stays in use/)).toBeInTheDocument();
    expect(repo.decline).toHaveBeenCalledWith(TOKEN);
    expect(repo.confirm).not.toHaveBeenCalled();
  });

  it('asks to open the email link again when the page has no token', async () => {
    const repo = render({}, '');
    expect(await screen.findByRole('alert')).toHaveTextContent(/open it from the email again/);
    expect(repo.lookup).not.toHaveBeenCalled();
  });

  it('retries a failed lookup with the token it already read', async () => {
    const lookup = vi
      .fn()
      .mockRejectedValueOnce(refused('RECORDING_UNAVAILABLE'))
      .mockResolvedValueOnce(details);
    render({ lookup });
    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }));
    expect(await screen.findByText(display)).toBeInTheDocument();
    expect(lookup).toHaveBeenNthCalledWith(2, TOKEN);
  });

  it('offers no retry for a used link', async () => {
    render({ lookup: vi.fn().mockRejectedValue(refused('LINK_INVALID')) });
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /already confirmed it, your new key is active/
    );
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
  });

  it.each([
    ['LINK_INVALID', /not valid or has already been used/],
    ['LINK_EXPIRED', /has expired/],
    ['RECORDING_UNAVAILABLE', /did not work/],
  ])('explains a refused lookup (%s)', async (code, message) => {
    render({ lookup: vi.fn().mockRejectedValue(refused(code)) });
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.queryByRole('button', { name: 'Confirm key' })).not.toBeInTheDocument();
  });

  it('keeps the buttons after a ceremony refusal, so the user can try again', async () => {
    const confirm = vi
      .fn()
      .mockRejectedValueOnce(refused('CEREMONY_IN_PROGRESS'))
      .mockResolvedValueOnce({ fingerprint: new Uint8Array(32), fingerprintDisplay: display });
    render({ confirm });
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm key' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/key ceremony/);
    await userEvent.click(screen.getByRole('button', { name: 'Confirm key' }));
    expect(await screen.findByText('Your new key is active.')).toBeInTheDocument();
  });

  it('ends at an expired link even after it was shown', async () => {
    render({ confirm: vi.fn().mockRejectedValue(refused('LINK_EXPIRED')) });
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm key' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/has expired/);
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Confirm key' })).not.toBeInTheDocument()
    );
  });

  it('disables both buttons while a call runs', async () => {
    let finish: (value: unknown) => void = () => undefined;
    const confirm = vi.fn().mockReturnValue(new Promise((resolve) => (finish = resolve)));
    render({ confirm });
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm key' }));
    expect(screen.getByRole('button', { name: 'Confirm key' })).toBeDisabled();
    expect(screen.getByRole('button', { name: "This wasn't me" })).toBeDisabled();
    finish({ fingerprint: new Uint8Array(32), fingerprintDisplay: display });
    expect(await screen.findByText('Your new key is active.')).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledOnce();
  });
});
