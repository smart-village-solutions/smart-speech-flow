import axios from 'axios';

export type AppErrorKind =
  | 'network'
  | 'timeout'
  | 'notFound'
  | 'validation'
  | 'server'
  | 'unknown';

const KIND_MESSAGE_KEYS: Record<AppErrorKind, string> = {
  network: 'errors.network',
  timeout: 'errors.timeout',
  notFound: 'errors.notFound',
  validation: 'errors.validation',
  server: 'errors.server',
  unknown: 'errors.unknown',
};

interface AppErrorOptions {
  status?: number;
  correlationId?: string;
  cause?: unknown;
}

/** The only error type that crosses the domain boundary into features. */
export class AppError extends Error {
  readonly kind: AppErrorKind;
  readonly userMessageKey: string;
  readonly status?: number;
  readonly correlationId?: string;

  constructor(kind: AppErrorKind, options: AppErrorOptions = {}) {
    super(`AppError(${kind})`, { cause: options.cause });
    this.name = 'AppError';
    this.kind = kind;
    this.userMessageKey = KIND_MESSAGE_KEYS[kind];
    this.status = options.status;
    this.correlationId = options.correlationId;
  }
}

export function toAppError(error: unknown): AppError {
  if (error instanceof AppError) {
    return error;
  }

  if (!axios.isAxiosError(error)) {
    return new AppError('unknown', { cause: error });
  }

  const rawCorrelationId = error.config?.headers?.['X-Correlation-Id'];
  const correlationId = typeof rawCorrelationId === 'string' ? rawCorrelationId : undefined;

  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
    return new AppError('timeout', { correlationId, cause: error });
  }

  if (!error.response) {
    return new AppError('network', { correlationId, cause: error });
  }

  const status = error.response.status;

  if (status === 404) {
    return new AppError('notFound', { status, correlationId, cause: error });
  }

  if (status >= 400 && status < 500) {
    return new AppError('validation', { status, correlationId, cause: error });
  }

  return new AppError('server', { status, correlationId, cause: error });
}
