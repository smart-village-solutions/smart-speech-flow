import { describe, expect, it } from 'vitest';
import { trustChain } from '@/domain/recovery/chain.mapper';
import type { ServedGeneration } from '@/domain/recovery/recovery.types';

const generation = (overrides: Partial<ServedGeneration>): ServedGeneration => ({
  ceremonyId: 'c-1',
  kind: 'generation',
  k: 2,
  transcriptHash: new Uint8Array(32).fill(1),
  previousTranscript: null,
  gatewayKeys: [],
  participants: [],
  dealers: [1, 2],
  dealings: [],
  signatures: new Map(),
  ...overrides,
});

describe('trustChain', () => {
  it('gives each resharing the key it keeps and the generation it replaces', () => {
    const previous = new Uint8Array(32).fill(1);
    const chain = trustChain('tenant-kassel', {
      recoveryKeyId: 'c-1',
      firstTranscriptHash: previous,
      holdersCeremonyId: 'c-2',
      holdersTranscriptHash: previous,
      generations: [
        generation({}),
        generation({
          ceremonyId: 'c-2',
          kind: 'resharing',
          previousTranscript: previous,
          dealers: [1, 4],
        }),
      ],
    });
    expect(chain.generations[0].facts.resharing).toBeUndefined();
    expect(chain.generations[1].facts).toMatchObject({
      tenantId: 'tenant-kassel',
      ceremonyId: 'c-2',
      resharing: {
        recoveryKeyId: 'c-1',
        previousTranscript: previous,
        dealers: [1, 4],
        previous: null,
      },
    });
  });

  it('leaves a resharing without its previous transcript unlinked, so certifying it fails', () => {
    const chain = trustChain('t', {
      recoveryKeyId: 'c-1',
      firstTranscriptHash: new Uint8Array(32),
      holdersCeremonyId: 'c-1',
      holdersTranscriptHash: new Uint8Array(32),
      generations: [generation({ kind: 'resharing' })],
    });
    expect(chain.generations[0].facts.resharing).toBeUndefined();
  });
});
