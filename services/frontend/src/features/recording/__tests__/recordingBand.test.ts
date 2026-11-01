import { describe, expect, it, vi } from 'vitest';
import type { RecordingStatus } from '@/domain/recording/recordingSession.types';
import { initialRecording, recordingReducer, type RecordingSlice } from '../recording.slice';
import { bandView, elapsed, isLive, LIVENESS_MS } from '../recordingBand';
import { recordingEvents } from '../recordingEvents';

const status = (phase: RecordingStatus['phase'], extra: Partial<RecordingStatus> = {}) => ({
  phase,
  reason: null,
  windowId: phase === 'off' || phase === 'asking' ? null : 'w1',
  stateVersion: 3,
  since: 1_000,
  ...extra,
});

const slice = (phase: RecordingStatus['phase'], extra: Partial<RecordingStatus> = {}) =>
  ({ ...initialRecording, status: status(phase, extra), pingAt: 10_000 }) satisfies RecordingSlice;

describe('the recording slice', () => {
  it('never lets an older state undo a newer one', () => {
    const newer = recordingReducer(initialRecording, {
      type: 'recording/state',
      status: status('on', { stateVersion: 5 }),
    });
    const stale = recordingReducer(newer, {
      type: 'recording/state',
      status: status('asking', { stateVersion: 4 }),
    });
    expect(stale.status.phase).toBe('on');
  });

  it('drops the open question once the state moves on', () => {
    const asked = recordingReducer(
      recordingReducer(initialRecording, { type: 'recording/state', status: status('asking') }),
      { type: 'recording/request', request: { requestId: 'r1', consentKind: 'first' } }
    );
    expect(asked.request?.requestId).toBe('r1');
    const armed = recordingReducer(asked, {
      type: 'recording/state',
      status: status('arming', { stateVersion: 4 }),
    });
    expect(armed.request).toBeNull();
  });
});

describe('the recording frames', () => {
  it('acknowledges every state by its version and answers every ping', () => {
    const dispatch = vi.fn();
    const transport = { send: vi.fn() };
    const handlers = new Map(recordingEvents(dispatch, transport, () => 0));

    handlers.get('recording_state')?.({
      role: 'recording_state',
      state: 'on',
      reason: null,
      window_id: 'w1',
      state_version: 7,
      since: '2026-10-27T12:00:00+00:00',
    });
    handlers.get('recording_ping')?.({ role: 'recording_ping' });
    handlers.get('recording_state')?.({ role: 'recording_state', state: 'recording' });

    expect(transport.send.mock.calls).toEqual([
      [{ type: 'recording_state_ack', state_version: 7 }],
      [{ type: 'recording_pong' }],
    ]);
    expect(dispatch.mock.calls.map(([action]) => action.type)).toEqual([
      'recording/state',
      // A state frame is contact with the gateway as much as a ping is.
      'recording/ping',
      'recording/ping',
    ]);
  });

  it('neither applies nor acknowledges a state older than the one on screen', () => {
    const dispatch = vi.fn();
    const transport = { send: vi.fn() };
    const handlers = new Map(recordingEvents(dispatch, transport, () => 9));

    handlers.get('recording_state')?.({
      role: 'recording_state',
      state: 'on',
      reason: null,
      window_id: 'w1',
      state_version: 7,
      since: null,
    });

    expect(dispatch).not.toHaveBeenCalled();
    expect(transport.send).not.toHaveBeenCalled();
  });
});

describe('the band', () => {
  it('is live only on a connected socket with a recent ping', () => {
    const on = slice('on');
    expect(isLive(on, 'connected', 10_000 + LIVENESS_MS - 1)).toBe(true);
    expect(isLive(on, 'connected', 10_000 + LIVENESS_MS)).toBe(false);
    expect(isLive(on, 'disconnected', 10_001)).toBe(false);
    expect(isLive({ ...on, pingAt: null }, 'connected', 10_001)).toBe(false);
  });

  it('shows recording only while on and live, and paused otherwise', () => {
    expect(bandView('customer', slice('on'), true, false)).toMatchObject({
      variant: 'live',
      labelKey: 'recording.label',
      since: 1_000,
      action: 'stop',
    });
    expect(bandView('customer', slice('on'), false, false)).toMatchObject({
      variant: 'neutral',
      labelKey: 'recording.paused',
      detailKey: 'recording.reason.liveness',
    });
    expect(bandView('admin', slice('paused', { reason: 'storage' }), true, true)).toMatchObject({
      detailKey: 'recording.reason.storage',
      action: 'stop',
    });
  });

  it('lets either side stop while recording is starting', () => {
    expect(bandView('customer', slice('arming'), true, false)?.action).toBe('stop');
    expect(bandView('admin', slice('arming'), true, true)?.action).toBe('stop');
  });

  it('gives the guest no band while off or asked, and the admin the request', () => {
    expect(bandView('customer', slice('off'), false, false)).toBeNull();
    expect(bandView('customer', slice('asking'), false, false)).toBeNull();
    expect(bandView('admin', slice('off'), false, false)).toBeNull();
    expect(bandView('admin', slice('off'), false, true)).toMatchObject({
      labelKey: 'admin.recording.off',
      action: 'request',
    });
    expect(bandView('admin', slice('off', { reason: 'declined' }), false, true)?.labelKey).toBe(
      'admin.recording.reason.declined'
    );
    expect(bandView('admin', slice('asking'), false, true)?.action).toBe('cancel');
  });

  it('counts minutes and seconds, zero-padded', () => {
    expect(elapsed(0, 61_999)).toBe('01:01');
    expect(elapsed(0, 3_600_000)).toBe('60:00');
    expect(elapsed(5_000, 0)).toBe('00:00');
  });
});

describe('Studio recording status wording', () => {
  const copy = {
    locale: 'de',
    waiting: 'Studio waiting',
    running: 'Studio running',
    stopped: 'Studio stopped',
    renewedReleaseRequired: 'Release again',
  };
  it('uses matching wording while keeping the controls', () => {
    expect(bandView('admin', slice('asking'), true, true, copy)).toMatchObject({
      labelText: copy.waiting,
      action: 'cancel',
    });
    expect(bandView('customer', slice('on'), true, false, copy)).toMatchObject({
      labelText: copy.running,
      action: 'stop',
    });
    expect(
      bandView('customer', slice('off', { reason: 'stopped_by_employee' }), true, false, copy)
    ).toMatchObject({
      labelText: copy.stopped,
      detailText: copy.renewedReleaseRequired,
      action: null,
    });
    expect(
      bandView('admin', slice('off', { reason: 'stopped_by_guest' }), true, true, copy)
    ).toMatchObject({ labelText: copy.stopped, action: 'request' });
  });
  it('keeps bundled pause reasons when liveness fails and never calls a refusal stopped', () => {
    expect(bandView('customer', slice('on'), false, false, copy)).toMatchObject({
      labelKey: 'recording.paused',
      detailKey: 'recording.reason.liveness',
    });
    expect(bandView('customer', slice('on'), false, false, copy)).not.toHaveProperty('labelText');
    expect(
      bandView('customer', slice('off', { reason: 'declined' }), true, false, copy)
    ).toBeNull();
    expect(
      bandView('admin', slice('off', { reason: 'declined' }), true, true, copy)
    ).not.toHaveProperty('labelText');
  });
});
