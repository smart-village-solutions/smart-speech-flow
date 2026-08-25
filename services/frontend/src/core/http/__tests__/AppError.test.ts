import { AxiosError, AxiosHeaders } from 'axios';
import { describe, expect, it } from 'vitest';
import { AppError, toAppError } from '@/core/http/AppError';

function axiosErrorWithStatus(status: number): AxiosError {
  const error = new AxiosError('boom', 'ERR_BAD_RESPONSE');
  error.config = { headers: new AxiosHeaders({ 'X-Correlation-Id': 'cid-1' }) };
  error.response = {
    status,
    statusText: '',
    data: {},
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
});
