import { AxiosError, AxiosHeaders } from 'axios';
import { describe, expect, it } from 'vitest';
import { AppError, toAppError } from '@/core/http/AppError';

function axiosErrorWithStatus(status: number, data: unknown = {}): AxiosError {
  const error = new AxiosError('boom', 'ERR_BAD_RESPONSE');
  error.config = { headers: new AxiosHeaders({ 'X-Correlation-Id': 'cid-1' }) };
  error.response = {
    status,
    statusText: '',
    data,
    headers: {},
    config: error.config,
  };
  return error;
}

describe('toAppError', () => {
  it('maps 404 to notFound and keeps the correlation id', () => {
    const result = toAppError(axiosErrorWithStatus(404));
    expect(result.kind).toBe('notFound');
    expect(result.userMessageKey).toBe('errors.notFound');
    expect(result.correlationId).toBe('cid-1');
  });

  it('maps other 4xx to validation', () => {
    expect(toAppError(axiosErrorWithStatus(400)).kind).toBe('validation');
  });

  it('maps 5xx to server', () => {
    expect(toAppError(axiosErrorWithStatus(503)).kind).toBe('server');
  });

  it('reads a 422 that names NO_SPEECH_RECOGNIZED as noSpeech', () => {
    const result = toAppError(
      axiosErrorWithStatus(422, {
        detail: {
          status: 'error',
          error_code: 'NO_SPEECH_RECOGNIZED',
          error_message: 'No speech was recognised in the recording.',
          details: {},
          timestamp: '2026-10-01T00:00:00Z',
        },
      })
    );

    expect(result.kind).toBe('noSpeech');
    expect(result.serverCode).toBe('NO_SPEECH_RECOGNIZED');
    expect(result.userMessageKey).toBe('errors.noSpeech');
    expect(result.retryable).toBe(false);
  });

  it('keeps a FastAPI field-validation 422 as validation', () => {
    // FastAPI answers 422 for invalid request fields on the same route, so
    // the status alone never means "no speech".
    const result = toAppError(
      axiosErrorWithStatus(422, {
        detail: [{ loc: ['body', 'text'], msg: 'too short', type: 'string_too_short' }],
      })
    );

    expect(result.kind).toBe('validation');
    expect(result.serverCode).toBeUndefined();
  });

  it('keeps an unknown or inherited-looking code as validation', () => {
    for (const code of ['SOMETHING_ELSE', 'constructor', 'toString']) {
      const result = toAppError(axiosErrorWithStatus(422, { detail: { error_code: code } }));

      expect(result.kind).toBe('validation');
      expect(result.serverCode).toBe(code);
    }
  });

  it('keeps a 5xx as server whatever code it carries', () => {
    const result = toAppError(
      axiosErrorWithStatus(500, { detail: { error_code: 'NO_SPEECH_RECOGNIZED' } })
    );

    expect(result.kind).toBe('server');
  });

  it('maps a response-less axios error to network', () => {
    const error = new AxiosError('offline', 'ERR_NETWORK');
    expect(toAppError(error).kind).toBe('network');
  });

  it('maps an aborted request to timeout', () => {
    const error = new AxiosError('timeout', 'ECONNABORTED');
    expect(toAppError(error).kind).toBe('timeout');
  });

  it('maps anything else to unknown', () => {
    expect(toAppError(new Error('nope')).kind).toBe('unknown');
  });

  it('passes an AppError through unchanged', () => {
    const original = new AppError('server');
    expect(toAppError(original)).toBe(original);
  });

  it('treats a throttle as retryable even though it maps to validation', () => {
    // The gateway's rate limiter answers 429 with Retry-After: the server is
    // asking for one more attempt, not rejecting the payload. Every 4xx that
    // is not 404 lands in `validation`, so the kind alone cannot tell them
    // apart.
    const throttled = toAppError(axiosErrorWithStatus(429));

    expect(throttled.kind).toBe('validation');
    expect(throttled.retryable).toBe(true);
  });

  it.each([400, 404, 409, 422])('treats %i as the server\'s verdict on the payload', (status) => {
    expect(toAppError(axiosErrorWithStatus(status)).retryable).toBe(false);
  });

  it.each([500, 502, 503])('treats %i as worth another attempt', (status) => {
    expect(toAppError(axiosErrorWithStatus(status)).retryable).toBe(true);
  });

  it('has no status to judge a transport failure by, so it allows a retry', () => {
    expect(new AppError('network').retryable).toBe(true);
    expect(new AppError('timeout').retryable).toBe(true);
  });
});
