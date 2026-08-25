import type { ConsentSink } from './consent.port';
import type { ConsentRecord } from './consent.types';

export function createStubConsentSink(
  recorder: (record: ConsentRecord) => void = () => {}
): ConsentSink {
  return {
    async record(record) {
      recorder(record);
    },
  };
}
