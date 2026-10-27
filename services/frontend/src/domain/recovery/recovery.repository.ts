import type { AxiosInstance } from 'axios';
import { type Bytes, scalarToBytes, toBase64Url } from '@/core/crypto/bytes';
import type { Confirmation } from '@/core/crypto/ceremony-crypto.port';
import { toCandidates, toCeremony, toCeremonyState, toSubshares } from './recovery.mapper';
import type {
  AbortReason,
  Ceremony,
  CeremonyState,
  CustodianCandidate,
  NewDealing,
  ReceivedSubshares,
} from './recovery.types';

const BASE = '/api/admin/recording/ceremony';

export interface RecoveryCeremonyRepository {
  state(): Promise<CeremonyState>;
  candidates(): Promise<CustodianCandidate[]>;
  start(k: number, custodians: readonly string[], paperDevicePub: Bytes | null): Promise<Ceremony>;
  deal(ceremonyId: string, dealing: Readonly<NewDealing>): Promise<void>;
  subshares(ceremonyId: string): Promise<ReceivedSubshares>;
  confirm(ceremonyId: string, confirmation: Readonly<Confirmation>): Promise<void>;
  confirmPaper(ceremonyId: string, transcriptHash: Bytes): Promise<void>;
  abort(ceremonyId: string, reason: AbortReason): Promise<void>;
}

export function createRecoveryCeremonyRepository(http: AxiosInstance): RecoveryCeremonyRepository {
  return {
    async state() {
      return toCeremonyState((await http.get<unknown>(BASE)).data);
    },

    async candidates() {
      return toCandidates((await http.get<unknown>(`${BASE}/candidates`)).data);
    },

    async start(k, custodians, paperDevicePub) {
      const response = await http.post<unknown>(BASE, {
        k,
        custodians,
        paper_device_pub: paperDevicePub === null ? null : toBase64Url(paperDevicePub),
      });
      return toCeremony(response.data);
    },

    async deal(ceremonyId, dealing) {
      await http.post(`${BASE}/${ceremonyId}/dealings`, {
        commitments: dealing.commitments.map(toBase64Url),
        c: toBase64Url(scalarToBytes(dealing.proof.c)),
        s: toBase64Url(scalarToBytes(dealing.proof.s)),
        signature: toBase64Url(dealing.signature),
        subshares: Object.fromEntries([...dealing.subshares].map(([index, sealed]) => [String(index), sealed])),
      });
    },

    async subshares(ceremonyId) {
      return toSubshares((await http.get<unknown>(`${BASE}/${ceremonyId}/subshares`)).data);
    },

    async confirm(ceremonyId, confirmation) {
      await http.post(`${BASE}/${ceremonyId}/confirmations`, {
        transcript_signature: toBase64Url(confirmation.transcriptSignature),
        encrypted_share: confirmation.encryptedShare,
      });
    },

    async confirmPaper(ceremonyId, transcriptHash) {
      await http.post(`${BASE}/${ceremonyId}/paper-confirmation`, { transcript_hash: toBase64Url(transcriptHash) });
    },

    async abort(ceremonyId, reason) {
      await http.post(`${BASE}/${ceremonyId}/abort`, { reason });
    },
  };
}
