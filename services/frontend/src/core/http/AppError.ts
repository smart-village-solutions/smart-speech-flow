import axios from 'axios';

export type AppErrorKind =
  | 'network'
  | 'timeout'
  | 'notFound'
  | 'validation'
  | 'server'
  | 'noSpeech'
  | 'sessionHasGuest'
  | 'languageChanged'
  | 'unknown';

/**
 * Statuses the server itself asks to be retried, whatever kind they map to.
 *
 * `toAppError` buckets every 4xx that is not 404 into `validation`, so without
 * this a throttled request -- 429, sent with a Retry-After header by the
 * gateway's rate limiter -- would be reported as invalid input and refused a
 * second attempt the server explicitly invited.
 */
const RETRYABLE_STATUSES = new Set([408, 425, 429]);

/**
 * Whether sending the same request again could ever succeed, for errors that
 * carry no status: a transport failure has no verdict attached.
 */
const KIND_IS_RETRYABLE: Record<AppErrorKind, boolean> = {
  network: true,
  timeout: true,
  notFound: false,
  validation: false,
  server: true,
  noSpeech: false,
  sessionHasGuest: false,
  languageChanged: false,
  unknown: true,
};

const KIND_MESSAGE_KEYS: Record<AppErrorKind, string> = {
  network: 'errors.network',
  timeout: 'errors.timeout',
  notFound: 'errors.notFound',
  validation: 'errors.validation',
  server: 'errors.server',
  noSpeech: 'errors.noSpeech',
  sessionHasGuest: 'accessCode.sessionHasGuest',
  languageChanged: 'errors.languageChanged',
  unknown: 'errors.unknown',
};

/** Server error codes that name a kind of their own; matched only on a 4xx. */
const KIND_BY_SERVER_CODE: ReadonlyMap<string, AppErrorKind> = new Map([
  ['NO_SPEECH_RECOGNIZED', 'noSpeech'],
  ['SESSION_HAS_GUEST', 'sessionHasGuest'],
  // The session's languages changed under this screen; the conversation refetches them.
  ['INVALID_SOURCE_LANGUAGE', 'languageChanged'],
  ['INVALID_TARGET_LANGUAGE', 'languageChanged'],
]);

interface AppErrorOptions {
  status?: number;
  correlationId?: string;
  serverCode?: string;
  cause?: unknown;
}

function isRetryable(kind: AppErrorKind, status?: number): boolean {
  if (status !== undefined) {
    if (RETRYABLE_STATUSES.has(status)) {
      return true;
    }
    // Any other 4xx is the server's verdict on this exact payload; repeating
    // it unchanged fails the same way.
    if (status >= 400 && status < 500) {
      return false;
    }
  }
  return KIND_IS_RETRYABLE[kind];
}

/** The only error type that crosses the domain boundary into features. */
export class AppError extends Error {
  readonly kind: AppErrorKind;
  readonly userMessageKey: string;
  readonly retryable: boolean;
  readonly status?: number;
  readonly correlationId?: string;
  readonly serverCode?: string;

  constructor(kind: AppErrorKind, options: AppErrorOptions = {}) {
    super(`AppError(${kind})`, { cause: options.cause });
    this.name = 'AppError';
    this.kind = kind;
    this.userMessageKey = KIND_MESSAGE_KEYS[kind];
    this.retryable = isRetryable(kind, options.status);
    this.status = options.status;
    this.correlationId = options.correlationId;
    this.serverCode = options.serverCode;
  }
}

/** A JSON error body that arrived as bytes, as it does for a binary download. */
function decodedBody(data: unknown): unknown {
  // A tag check, not instanceof: the buffer may come from another realm (a worker, a test).
  if (Object.prototype.toString.call(data) !== '[object ArrayBuffer]') return data;
  try {
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(data as ArrayBuffer));
  } catch {
    return undefined;
  }
}

/** The gateway's `detail.error_code`, when `detail` is its error envelope. */
function serverErrorCode(raw: unknown): string | undefined {
  const data = decodedBody(raw);
  if (typeof data !== 'object' || data === null) {
    return undefined;
  }
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail !== 'object' || detail === null || Array.isArray(detail)) {
    return undefined;
  }
  const code = (detail as { error_code?: unknown }).error_code;
  return typeof code === 'string' ? code : undefined;
}

const SESSION_NOT_FOUND = 'SESSION_NOT_FOUND';

/**
 * The session routes answer a plain `"Session not found"` detail, the message
 * routes the error envelope; both mean the gateway no longer has the session.
 */
function notFoundCode(data: unknown): string | undefined {
  const detail = (data as { detail?: unknown } | null)?.detail;
  return detail === 'Session not found' ? SESSION_NOT_FOUND : serverErrorCode(data);
}

/**
 * Whether the gateway itself said the session is gone. A bare 404 is not
 * enough: while the gateway is redeployed, the proxy in front answers 404 too.
 */
export function isSessionGone(error: unknown): boolean {
  return (
    error instanceof AppError && error.kind === 'notFound' && error.serverCode === SESSION_NOT_FOUND
  );
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
    const serverCode = notFoundCode(error.response.data);
    return new AppError('notFound', { status, correlationId, serverCode, cause: error });
  }

  if (status >= 400 && status < 500) {
    const serverCode = serverErrorCode(error.response.data);
    const kind = KIND_BY_SERVER_CODE.get(serverCode ?? '') ?? 'validation';
    return new AppError(kind, { status, correlationId, serverCode, cause: error });
  }

  return new AppError('server', {
    status,
    correlationId,
    serverCode: serverErrorCode(error.response.data),
    cause: error,
  });
}
