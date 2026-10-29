import type { AxiosInstance } from 'axios';
import { type Bytes, toBase64Url } from '@/core/crypto/bytes';
import type {
  NewRecoveredWrap,
  RecoveryIntegrityStage,
  Rejection,
  ScopePair,
} from '@/core/crypto/recovery-crypto.port';
import { AppError } from '@/core/http/AppError';
import {
  toApprovalDetail,
  toCandidates,
  toEmployees,
  toProgress,
  toScope,
  toServedPartials,
  toSummaries,
} from './requests.mapper';
import type {
  ApprovalDetail,
  RecoveryCandidate,
  RecoveryEmployee,
  RequestProgress,
  RequestSummary,
  ServedPartials,
} from './requests.types';

const BASE = '/api/admin/recording/recovery';

export interface FiledRequest {
  requestId: string;
  reason: string;
  conversationIds: readonly string[];
  signature: Bytes;
}

export interface RecoveryRequestsRepository {
  employees(): Promise<RecoveryEmployee[]>;
  candidates(employee: string, from: string, to: string): Promise<RecoveryCandidate[]>;
  file(request: Readonly<FiledRequest>): Promise<ScopePair[]>;
  requests(): Promise<RequestSummary[]>;
  progress(requestId: string): Promise<RequestProgress>;
  partials(requestId: string): Promise<ServedPartials>;
  reject(requestId: string, rejection: Readonly<Rejection>): Promise<void>;
  reportIntegrity(requestId: string, stage: RecoveryIntegrityStage | 'trust'): Promise<void>;
  storeWraps(requestId: string, wraps: readonly NewRecoveredWrap[]): Promise<string[]>;
  cancel(requestId: string): Promise<void>;
  approvals(): Promise<RequestSummary[]>;
  approval(requestId: string): Promise<ApprovalDetail>;
  approve(
    requestId: string,
    partials: ReadonlyMap<string, string>,
    signature: Bytes
  ): Promise<void>;
  decline(requestId: string, reason: string): Promise<void>;
}

/** A refusal the screens tell apart by its server code; anything else stays an AppError. */
export class RecoveryRefusedError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(`recovery refused: ${code}`);
    this.name = 'RecoveryRefusedError';
    this.code = code;
  }
}

async function refusals<T>(call: Promise<T>): Promise<T> {
  try {
    return await call;
  } catch (error) {
    if (
      error instanceof AppError &&
      error.serverCode &&
      error.status !== undefined &&
      error.status < 500
    ) {
      throw new RecoveryRefusedError(error.serverCode);
    }
    throw error;
  }
}

export function createRecoveryRequestsRepository(http: AxiosInstance): RecoveryRequestsRepository {
  const get = async (path: string, params?: Record<string, string>) =>
    (await refusals(http.get<unknown>(`${BASE}${path}`, { params }))).data;
  const post = async (path: string, body?: unknown) =>
    (await refusals(http.post<unknown>(`${BASE}${path}`, body))).data;

  return {
    employees: async () => toEmployees(await get('/employees')),
    candidates: async (employee, from, to) =>
      toCandidates(await get('/candidates', { employee, from, to })),
    file: async (request) =>
      toScope(
        await post('/requests', {
          request_id: request.requestId,
          reason: request.reason,
          conversation_ids: request.conversationIds,
          signature: toBase64Url(request.signature),
        })
      ),
    requests: async () => toSummaries(await get('/requests')),
    progress: async (requestId) => toProgress(await get(`/requests/${requestId}`)),
    partials: async (requestId) => toServedPartials(await get(`/requests/${requestId}/partials`)),
    reject: async (requestId, rejection) => {
      await post(`/requests/${requestId}/rejections`, {
        holder_index: rejection.holderIndex,
        attempt: rejection.attempt,
        fault: rejection.fault,
      });
    },
    reportIntegrity: async (requestId, stage) => {
      await post(`/requests/${requestId}/integrity-failures`, { stage });
    },
    storeWraps: async (requestId, wraps) => {
      const body = await post(`/requests/${requestId}/wraps`, {
        wraps: wraps.map((w) => ({
          conversation_id: w.conversationId,
          key_id: w.keyId,
          blob: w.blob,
          signature: toBase64Url(w.signature),
        })),
      });
      return (body as { dropped: string[] }).dropped;
    },
    cancel: async (requestId) => {
      await post(`/requests/${requestId}/cancel`);
    },
    approvals: async () => toSummaries(await get('/approvals')),
    approval: async (requestId) => toApprovalDetail(await get(`/approvals/${requestId}`)),
    approve: async (requestId, partials, signature) => {
      await post(`/approvals/${requestId}`, {
        partials: Object.fromEntries(partials),
        signature: toBase64Url(signature),
      });
    },
    decline: async (requestId, reason) => {
      await post(`/approvals/${requestId}/decline`, { reason });
    },
  };
}
