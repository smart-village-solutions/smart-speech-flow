import type { AxiosInstance } from 'axios';
import { type Bytes, toBase64Url } from '@/core/crypto/bytes';
import { AppError } from '@/core/http/AppError';
import { toOpened, toOwnConversations, toTrust } from './archive.mapper';
import type { ArchiveTrust, OpenedConversation, OwnConversation } from './archive.types';

const BASE = '/api/admin/recording/archive';

/** The object is listed in the chain but the spool has not delivered it yet. */
export class ObjectNotStoredError extends Error {
  constructor() {
    super('object not stored yet');
    this.name = 'ObjectNotStoredError';
  }
}

/** The gateway serves objects for an hour after an audited open; open the conversation again. */
export class ConversationNotOpenError extends Error {
  constructor() {
    super('conversation not open');
    this.name = 'ConversationNotOpenError';
  }
}

/** The amendment is in the chain, but its ciphertext did not reach the spool: re-post it. */
export class AmendmentNotStoredError extends Error {
  constructor() {
    super('amendment not stored');
    this.name = 'AmendmentNotStoredError';
  }
}

export type IntegrityStage = 'trust' | 'wrap' | 'chain' | 'stamp' | 'object';

export interface ArchiveCursor {
  startedBefore: string;
  beforeId: string;
}

export interface AmendmentPost {
  entryId: string;
  keyId: string;
  ciphertext: Bytes;
}

export interface ArchiveRepository {
  list(cursor?: ArchiveCursor): Promise<OwnConversation[]>;
  open(conversationId: string): Promise<OpenedConversation>;
  trust(tenantId: string): Promise<ArchiveTrust>;
  object(conversationId: string, entryId: string, objectType: string): Promise<Bytes>;
  amend(
    conversationId: string,
    post: Readonly<AmendmentPost>
  ): Promise<{ entryId: string; seq: number }>;
  reportIntegrity(conversationId: string, stage: IntegrityStage): Promise<void>;
}

function hasCode(error: unknown, code: string): boolean {
  return error instanceof AppError && error.serverCode === code;
}

export function createArchiveRepository(http: AxiosInstance): ArchiveRepository {
  return {
    async list(cursor) {
      const params = cursor
        ? { started_before: cursor.startedBefore, before_id: cursor.beforeId }
        : {};
      return toOwnConversations((await http.get<unknown>(BASE, { params })).data);
    },

    async open(conversationId) {
      return toOpened((await http.get<unknown>(`${BASE}/${conversationId}`)).data);
    },

    async trust(tenantId) {
      return toTrust((await http.get<unknown>(`${BASE}/trust`)).data, tenantId);
    },

    async object(conversationId, entryId, objectType) {
      try {
        const response = await http.get<ArrayBuffer>(
          `${BASE}/${conversationId}/objects/${entryId}/${objectType}`,
          {
            responseType: 'arraybuffer',
          }
        );
        return new Uint8Array(response.data);
      } catch (error) {
        if (hasCode(error, 'OBJECT_NOT_STORED')) throw new ObjectNotStoredError();
        if (hasCode(error, 'CONVERSATION_NOT_FOUND')) throw new ConversationNotOpenError();
        throw error;
      }
    },

    async amend(conversationId, post) {
      try {
        const response = await http.post<{ entry_id: string; seq: number }>(
          `${BASE}/${conversationId}/amendments`,
          {
            entry_id: post.entryId,
            key_id: post.keyId,
            ciphertext: toBase64Url(post.ciphertext),
          }
        );
        return { entryId: response.data.entry_id, seq: response.data.seq };
      } catch (error) {
        if (hasCode(error, 'ARCHIVE_WRITE_FAILED')) throw new AmendmentNotStoredError();
        throw error;
      }
    },

    async reportIntegrity(conversationId, stage) {
      await http.post(`${BASE}/${conversationId}/integrity-failures`, { stage });
    },
  };
}
