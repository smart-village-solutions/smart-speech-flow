import type { RealtimeStatus } from '@/core/realtime/realtime.port';
import type { ClientRole } from '@/core/roles';
import type { RecordingStatusCopy } from '@/domain/content/content.types';
import type { RecordingSlice } from './recording.slice';

/** A screen that heard no ping for this long renders "paused" itself (spec §5.2). */
export const LIVENESS_MS = 12_000;

export type BandAction = 'request' | 'cancel' | 'stop';

export interface BandView {
  variant: 'live' | 'neutral';
  labelKey: string;
  labelText?: string;
  detailText?: string;
  language?: string;
  /** A second part after the label: why a recording is paused. */
  detailKey: string | null;
  /** Epoch ms the elapsed time counts from; live only. */
  since: number | null;
  action: BandAction | null;
}

/** Reasons the admin is told about while the recording is off. */
const ADMIN_OFF_REASONS = new Set(['declined', 'unanswered', 'stopped_by_guest']);

export function isLive(slice: RecordingSlice, connection: RealtimeStatus, now: number): boolean {
  return connection === 'connected' && slice.pingAt !== null && now - slice.pingAt < LIVENESS_MS;
}

function offView(slice: RecordingSlice, canRequest: boolean): BandView | null {
  if (!canRequest) {
    return null;
  }
  const { reason } = slice.status;
  const labelKey =
    reason !== null && ADMIN_OFF_REASONS.has(reason)
      ? `admin.recording.reason.${reason}`
      : 'admin.recording.off';
  return { variant: 'neutral', labelKey, detailKey: null, since: null, action: 'request' };
}

function pausedView(reason: string): BandView {
  return {
    variant: 'neutral',
    labelKey: 'recording.paused',
    detailKey: `recording.reason.${reason}`,
    since: null,
    action: 'stop',
  };
}

function neutral(labelKey: string, action: BandAction | null): BandView {
  return { variant: 'neutral', labelKey, detailKey: null, since: null, action };
}

/**
 * What the band shows, or null for no band (SCREEN_SPECS "Recording"). The
 * guest sees nothing while off, and the question instead of a band while asked.
 */
function bundledBandView(
  role: ClientRole,
  slice: RecordingSlice,
  live: boolean,
  canRequest: boolean
): BandView | null {
  const { phase, reason, since } = slice.status;
  switch (phase) {
    case 'off':
      return role === 'admin' ? offView(slice, canRequest) : null;
    case 'asking':
      return role === 'admin' ? neutral('admin.recording.waiting', 'cancel') : null;
    case 'arming':
      // Either side may stop at any time (spec §5.2), starting included.
      return neutral('recording.starting', 'stop');
    case 'on':
      return live
        ? { variant: 'live', labelKey: 'recording.label', detailKey: null, since, action: 'stop' }
        : pausedView('liveness');
    case 'paused':
      return pausedView(live ? (reason ?? 'liveness') : 'liveness');
  }
}

/** Studio copy only replaces the actual state it describes; pause reasons stay bundled. */
export function bandView(
  role: ClientRole,
  slice: RecordingSlice,
  live: boolean,
  canRequest: boolean,
  copy?: RecordingStatusCopy | null
): BandView | null {
  const view = bundledBandView(role, slice, live, canRequest);
  if (copy == null) return view;
  const { phase, reason } = slice.status;
  if (phase === 'off' && (reason === 'stopped_by_employee' || reason === 'stopped_by_guest')) {
    return {
      ...(view ?? neutral('admin.recording.off', null)),
      labelText: copy.stopped,
      detailText: copy.renewedReleaseRequired,
      language: copy.locale,
    };
  }
  if (view === null) return null;
  if (phase === 'asking') return { ...view, labelText: copy.waiting, language: copy.locale };
  if (phase === 'on' && live) return { ...view, labelText: copy.running, language: copy.locale };
  return view;
}

/** `MM:SS`, zero-padded; hours roll into the minutes. */
export function elapsed(since: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - since) / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}
