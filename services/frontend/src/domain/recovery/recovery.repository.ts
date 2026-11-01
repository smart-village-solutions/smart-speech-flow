import type { AxiosInstance } from 'axios';
import { type Bytes, scalarToBytes, toBase64Url } from '@/core/crypto/bytes';
import type { Confirmation } from '@/core/crypto/ceremony-crypto.port';
import { toCandidates, toCeremony, toCeremonyState, toDealerKey, toLeavers, toSubshares } from './recovery.mapper';
import type {
  AbortReason,
  Ceremony,
  CeremonyState,
  CustodianCandidate,
  DealerKey,
  LeaverCandidate,
  NewDealing,
  ReceivedSubshares,
} from './recovery.types';

const BASE = '/api/admin/recording/ceremony';
const LEAVERS = '/api/admin/recording/leavers';

export interface RecoveryCeremonyRepository {
  state(): Promise<CeremonyState>;
  candidates(): Promise<CustodianCandidate[]>;
  start(k: number, custodians: readonly string[], paperDevicePub: Bytes | null): Promise<Ceremony>;
  deal(ceremonyId: string, dealing: Readonly<NewDealing>): Promise<void>;
  subshares(ceremonyId: string): Promise<ReceivedSubshares>;
  confirm(ceremonyId: string, confirmation: Readonly<Confirmation>): Promise<void>;
  confirmPaper(ceremonyId: string, transcriptHash: Bytes): Promise<void>;
  abort(ceremonyId: string, reason: AbortReason): Promise<void>;
  startResharing(start: Readonly<ResharingStart>): Promise<Ceremony>;
  dealer(ceremonyId: string): Promise<DealerKey>;
  paperDeal(ceremonyId: string, dealerIndex: number, dealing: Readonly<NewDealing>): Promise<void>;
  /** Users with a key whom Studio no longer gives a recording permission (spec §9.8). */
  leavers(): Promise<LeaverCandidate[]>;
  /** Retires `keyVersion`, the version the list showed; needs a fresh MFA login. */
  markLeaver(sub: string, keyVersion: number): Promise<void>;
}

export interface ResharingStart {
  k: number;
  custodians: readonly string[];
  /** Old holder indices, exactly the current k. */
  dealers: readonly number[];
  /** The ceremony device's key, when a new paper backup is wanted. */
  paperDevicePub: Bytes | null;
  /** The generation the dealers were picked from; the gateway refuses another. */
  holdersCeremonyId: string;
}

function dealingBody(dealing: Readonly<NewDealing>) {
  return {
    commitments: dealing.commitments.map(toBase64Url),
    c: toBase64Url(scalarToBytes(dealing.proof.c)),
    s: toBase64Url(scalarToBytes(dealing.proof.s)),
    subshares: Object.fromEntries([...dealing.subshares].map(([index, sealed]) => [String(index), sealed])),
  };
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
      const signature = dealing.signature === null ? undefined : toBase64Url(dealing.signature);
      await http.post(`${BASE}/${ceremonyId}/dealings`, { ...dealingBody(dealing), signature });
    },

    async subshares(ceremonyId) {
      return toSubshares((await http.get<unknown>(`${BASE}/${ceremonyId}/subshares`)).data);
    },

    async confirm(ceremonyId, confirmation) {
      const proof = confirmation.shareProof;
      await http.post(`${BASE}/${ceremonyId}/confirmations`, {
        transcript_signature: toBase64Url(confirmation.transcriptSignature),
        encrypted_share: confirmation.encryptedShare,
        share_proof_c: proof === null ? undefined : toBase64Url(scalarToBytes(proof.c)),
        share_proof_s: proof === null ? undefined : toBase64Url(scalarToBytes(proof.s)),
      });
    },

    async confirmPaper(ceremonyId, transcriptHash) {
      await http.post(`${BASE}/${ceremonyId}/paper-confirmation`, { transcript_hash: toBase64Url(transcriptHash) });
    },

    async abort(ceremonyId, reason) {
      await http.post(`${BASE}/${ceremonyId}/abort`, { reason });
    },

    async startResharing(start) {
      const response = await http.post<unknown>(`${BASE}/resharing`, {
        k: start.k,
        custodians: start.custodians,
        dealers: start.dealers,
        paper_device_pub: start.paperDevicePub === null ? null : toBase64Url(start.paperDevicePub),
        holders_ceremony_id: start.holdersCeremonyId,
      });
      return toCeremony(response.data);
    },

    async dealer(ceremonyId) {
      return toDealerKey((await http.get<unknown>(`${BASE}/${ceremonyId}/dealer`)).data);
    },

    async paperDeal(ceremonyId, dealerIndex, dealing) {
      await http.post(`${BASE}/${ceremonyId}/paper-dealings`, { dealer_index: dealerIndex, ...dealingBody(dealing) });
    },

    async leavers() {
      return toLeavers((await http.get<unknown>(LEAVERS)).data);
    },

    async markLeaver(sub, keyVersion) {
      await http.post(`${LEAVERS}/${encodeURIComponent(sub)}`, { key_version: keyVersion });
    },
  };
}
