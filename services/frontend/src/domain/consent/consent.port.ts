import type { ConsentRecord } from './consent.types';

/**
 * POST /api/customer/session/activate does not accept a consent field yet
 * (docs/frontend/API_GAPS.md).
 */
export interface ConsentSink {
  record(record: ConsentRecord): Promise<void>;
}
