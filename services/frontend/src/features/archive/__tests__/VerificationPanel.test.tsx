import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminIdentity, hasFreshStepUp } from '@/app/auth/keycloak';
import type { ArchiveCrypto, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { displayFingerprint, fingerprint } from '@/core/crypto/transcript';
import { AppError } from '@/core/http/AppError';
import type { ArchiveRepository } from '@/domain/archive/archive.repository';
import type { ReviewerCandidate, VerificationRecord } from '@/domain/archive/archive.types';
import type { RecordingKeysRepository } from '@/domain/recording/recording.repository';
import type { Opened } from '@/features/archive/openConversation';
import { buildTimeline } from '@/features/archive/timeline';
import { VerificationPanel } from '@/features/archive/VerificationPanel';
import type { RecordView } from '@/features/archive/verifyRecords';
import de from '@/i18n/locales/de.json';
import { renderWithProviders } from '@/test/renderWithProviders';
import { IDS, loadedFixture, openedConversation } from './archiveFixture';

vi.mock('@/app/auth/keycloak', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/auth/keycloak')>()),
  getAdminIdentity: vi.fn(),
  hasFreshStepUp: vi.fn(),
}));

const v = de.admin.archive.verification;
const keys = new Map([[IDS.key, {} as CryptoKey]]);

const ENC_PUB = new Uint8Array(65).fill(4);
const SIG_PUB = new Uint8Array(65).fill(5);

/** A candidate whose fingerprint matches its keys, unless `forged`. */
async function candidate(
  sub: string,
  languages: string[],
  sworn = false,
  forged = false
): Promise<ReviewerCandidate> {
  const real = await fingerprint('tenant-kassel', sub, ENC_PUB, SIG_PUB);
  return {
    sub,
    displayName: sub.toUpperCase(),
    languages,
    sworn,
    keyVersion: 3,
    fingerprint: forged ? new Uint8Array(32).fill(1) : real,
    fingerprintDisplay: `SERVED-${sub}`,
    encPub: ENC_PUB,
    sigPub: SIG_PUB,
  };
}

function record(
  sub: string,
  status: VerificationRecord['status'],
  changes: Partial<VerificationRecord> = {}
): VerificationRecord {
  return {
    verificationId: `v-${sub}`,
    status,
    requestedBy: 'alice',
    requestedAt: '2026-11-02T10:00:00+00:00',
    reviewerSub: sub,
    reviewerName: sub.toUpperCase(),
    reviewerKeyVersion: 1,
    reviewerFingerprint: new Uint8Array(32),
    startedAt: null,
    reviewedHeadSeq: null,
    reviewedHead: null,
    permissionSnapshot: null,
    decidedAt: null,
    closedAt: null,
    closeReason: null,
    decided: null,
    ...changes,
  };
}

function ready(
  options: { allKeys?: boolean; records?: RecordView[] } = {}
): Extract<Opened, { status: 'ready' }> {
  const opened = openedConversation();
  const usable =
    options.allKeys === false ? opened.keys : opened.keys.filter((key) => key.wrap !== null);
  return {
    status: 'ready',
    opened: { ...opened, keys: usable },
    keys,
    stamps: [],
    signers: new Map([['gk-1', new Uint8Array(65)]]),
    records: options.records ?? [],
    view: buildTimeline(opened, loadedFixture(), keys),
  };
}

function render(
  state = ready(),
  overrides: { assign?: ArchiveRepository['assign']; forged?: boolean } = {}
) {
  const onChanged = vi.fn();
  const archive = {
    reviewers: vi
      .fn()
      .mockImplementation(async () => [
        await candidate('rita', ['ar', 'de'], true, overrides.forged),
        await candidate('ralf', ['de']),
      ]),
    assign: overrides.assign ?? vi.fn().mockResolvedValue(record('rita', 'awaiting')),
  } as unknown as ArchiveRepository;
  const archiveCrypto = {
    rewrapFor: vi
      .fn()
      .mockImplementation((wrap) =>
        Promise.resolve({ keyId: wrap.keyId, blob: '{}', signature: new Uint8Array(64) })
      ),
  } as unknown as ArchiveCrypto;
  const recordingKeys = {
    ownKey: vi.fn().mockResolvedValue({ keyVersion: 2 }),
  } as unknown as RecordingKeysRepository;
  renderWithProviders(
    <VerificationPanel state={state} unlocked={{} as UnlockedKeys} onChanged={onChanged} />,
    {
      locale: 'de',
      services: { archive, archiveCrypto, recordingKeys },
    }
  );
  return { archive, archiveCrypto, onChanged };
}

describe('VerificationPanel (spec §10.7)', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    vi.mocked(hasFreshStepUp).mockReturnValue(true);
  });

  it('withholds the request while a part of the conversation is not open to the caller', () => {
    render(ready({ allKeys: false }));
    expect(screen.queryByRole('button', { name: v.request })).not.toBeInTheDocument();
    expect(screen.getByText(v.missingKeys)).toBeInTheDocument();
  });

  it('asks for a fresh second factor before anything else', async () => {
    vi.mocked(hasFreshStepUp).mockReturnValue(false);
    const { archive } = render();
    await userEvent.click(screen.getByRole('button', { name: v.request }));
    expect(screen.getByText(v.stepUpBody)).toBeInTheDocument();
    expect(archive.reviewers).not.toHaveBeenCalled();
  });

  it('lists reviewers covering every language, and all on request', async () => {
    render();
    await userEvent.click(screen.getByRole('button', { name: v.request }));
    expect(await screen.findByText('RITA')).toBeInTheDocument();
    expect(screen.queryByText('RALF')).not.toBeInTheDocument();
    expect(screen.getByText(v.sworn)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(v.allReviewers));
    expect(screen.getByText('RALF')).toBeInTheDocument();
  });

  it('shows the fingerprint, wraps every key for the reviewer and assigns', async () => {
    const { archive, archiveCrypto, onChanged } = render();
    await userEvent.click(screen.getByRole('button', { name: v.request }));
    await userEvent.click(await screen.findByRole('radio'));
    await userEvent.click(screen.getByRole('button', { name: v.next }));
    const computed = displayFingerprint(
      await fingerprint('tenant-kassel', 'rita', ENC_PUB, SIG_PUB)
    );
    expect(await screen.findByText(computed)).toBeInTheDocument();
    expect(screen.queryByText('SERVED-rita')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: v.assign }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(archiveCrypto.rewrapFor).toHaveBeenCalledWith(
      expect.objectContaining({ keyId: IDS.key, recipientRef: 'alice' }),
      {},
      ready().signers,
      expect.objectContaining({ sub: 'rita' })
    );
    expect(archive.assign).toHaveBeenCalledWith(IDS.conversation, {
      keyVersion: 2,
      reviewerSub: 'rita',
      reviewerKeyVersion: 3,
      wraps: [{ keyId: IDS.key, blob: '{}', signature: new Uint8Array(64) }],
    });
  });

  it.each([
    ['REVIEWER_NOT_ELIGIBLE', v.error.REVIEWER_NOT_ELIGIBLE],
    ['SOMETHING_NEW', v.error.FAILED],
  ])('says why an assignment was refused (%s)', async (code, message) => {
    render(ready(), {
      assign: vi
        .fn()
        .mockRejectedValue(new AppError('validation', { status: 409, serverCode: code })),
    });
    await userEvent.click(screen.getByRole('button', { name: v.request }));
    await userEvent.click(await screen.findByRole('radio'));
    await userEvent.click(screen.getByRole('button', { name: v.next }));
    await userEvent.click(screen.getByRole('button', { name: v.assign }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
  });

  it('turns a late step-up refusal into the step-up prompt', async () => {
    render(ready(), {
      assign: vi
        .fn()
        .mockRejectedValue(
          new AppError('validation', { status: 403, serverCode: 'STEP_UP_REQUIRED' })
        ),
    });
    await userEvent.click(screen.getByRole('button', { name: v.request }));
    await userEvent.click(await screen.findByRole('radio'));
    await userEvent.click(screen.getByRole('button', { name: v.next }));
    await userEvent.click(screen.getByRole('button', { name: v.assign }));
    expect(await screen.findByText(v.stepUpBody)).toBeInTheDocument();
  });

  it('lists records with their state, and offers reassigning a declined one', async () => {
    const decided: RecordView = {
      record: record('rita', 'approved', {
        decidedAt: '2026-11-02T11:00:00+00:00',
        permissionSnapshot: ['ssf.recording.review', 'ssf.recording.review.sworn'],
      }),
      state: 'verified',
      overall: 'Insgesamt gut.',
      findings: new Map(),
      missingKeys: false,
      stampTime: null,
      entriesAfter: 2,
    };
    const declined: RecordView = {
      ...decided,
      record: record('ralf', 'declined', { closeReason: 'declined' }),
      state: 'closed',
      overall: null,
      entriesAfter: 0,
    };
    const broken: RecordView = {
      ...decided,
      record: record('rosa', 'not_approved'),
      state: 'broken',
      overall: null,
    };
    const { archive } = render(ready({ records: [decided, declined, broken] }));
    expect(screen.getByText('Insgesamt gut.')).toBeInTheDocument();
    expect(screen.getByText(v.sworn)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(v.olderHead.replace('{{count}}', '2')))).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(v.broken);
    expect(screen.queryByText(v.state.not_approved)).not.toBeInTheDocument(); // a broken record shows no outcome
    await userEvent.click(screen.getByRole('button', { name: v.reassign }));
    await waitFor(() => expect(archive.reviewers).toHaveBeenCalled());
  });
});

describe('VerificationPanel: the reviewer fingerprint (M2)', () => {
  beforeEach(() => {
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    vi.mocked(hasFreshStepUp).mockReturnValue(true);
  });

  it('refuses keys that do not match the fingerprint served for them', async () => {
    const { archive, archiveCrypto } = render(ready(), { forged: true });
    await userEvent.click(screen.getByRole('button', { name: v.request }));
    await userEvent.click(await screen.findByRole('radio'));
    await userEvent.click(screen.getByRole('button', { name: v.next }));
    expect(await screen.findByRole('alert')).toHaveTextContent(v.error.FINGERPRINT_MISMATCH);
    expect(screen.queryByRole('button', { name: v.assign })).not.toBeInTheDocument();
    expect(archiveCrypto.rewrapFor).not.toHaveBeenCalled();
    expect(archive.assign).not.toHaveBeenCalled();
  });
});

describe('FindingsColumns (AC3: side by side)', () => {
  it('shows each decided reviewer’s findings on an entry in its own column, never a broken one’s', async () => {
    const { FindingsColumns } = await import('@/features/archive/FindingsColumns');
    const finding = (text: string) => ({
      category: 'omission' as const,
      text,
      suggestion: 'Ergänzen',
    });
    const view = (
      sub: string,
      status: VerificationRecord['status'],
      state: RecordView['state'],
      text: string
    ): RecordView => ({
      record: record(sub, status),
      state,
      overall: null,
      findings: new Map([[IDS.message, [finding(text), finding(text)]]]),
      missingKeys: false,
      stampTime: null,
      entriesAfter: 0,
    });
    renderWithProviders(
      <FindingsColumns
        entryId={IDS.message}
        records={[
          view('rita', 'approved', 'verified', 'Kleine Lücke'),
          view('ralf', 'not_approved', 'verified', 'Satz fehlt ganz'),
          view('rosa', 'approved', 'broken', 'Darf nicht erscheinen'),
        ]}
      />,
      { locale: 'de' }
    );
    expect(screen.getAllByRole('heading')).toHaveLength(2);
    expect(screen.getAllByText('Kleine Lücke')).toHaveLength(2);
    expect(screen.getAllByText('Satz fehlt ganz')).toHaveLength(2);
    expect(screen.queryByText('Darf nicht erscheinen')).not.toBeInTheDocument();
    expect(screen.getAllByText(v.category.omission)).toHaveLength(4); // identical findings stay two rows
  });
});
