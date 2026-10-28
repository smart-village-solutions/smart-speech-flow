import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { RecordingSessionRepository } from '@/domain/recording/recordingSession.repository';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useConsentText } from '../useConsentText';

function Shown() {
  const [language, setLanguage] = useState('ar');
  const { consent } = useConsentText('A1B2C3D4', 'r-1', language);
  return (
    <>
      <p>{consent?.text.language ?? 'none'}</p>
      <button type="button" onClick={() => setLanguage('fa')}>
        switch
      </button>
    </>
  );
}

describe('useConsentText', () => {
  it('reads the text again in the language the guest switched to', async () => {
    const consentText = vi.fn(async () => ({
      requestId: 'r-1',
      consentKind: 'first' as const,
      language: consentText.mock.calls.length > 1 ? 'fa' : 'ar',
      html: '<p>x</p>',
      signature: 'off' as const,
      proposedName: null,
    }));
    const services = {
      recordingSession: { consentText } as unknown as RecordingSessionRepository,
    };
    renderWithProviders(<Shown />, { services });
    expect(await screen.findByText('ar')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'switch' }));

    expect(await screen.findByText('fa')).toBeInTheDocument();
    expect(consentText).toHaveBeenCalledTimes(2);
  });
});
