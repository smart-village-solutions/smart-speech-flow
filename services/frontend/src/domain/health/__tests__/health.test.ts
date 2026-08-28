import { describe, expect, it } from 'vitest';
import { toSystemLoad } from '@/domain/health/health.mapper';
import type { HealthSummaryDto } from '@/domain/health/health.mapper';

const healthy: HealthSummaryDto = {
  overall_healthy: true,
  summary: {
    service_mode: 'full',
    circuit_states: { asr: 'closed', translation: 'closed', tts: 'closed' },
    gpu: { critical_devices: 0, warning_devices: 0, recommended_action: 'steady' },
  },
};

const withSummary = (patch: Partial<NonNullable<HealthSummaryDto['summary']>>): HealthSummaryDto => ({
  ...healthy,
  summary: { ...healthy.summary, ...patch },
});

describe('toSystemLoad', () => {
  it('is ok when everything is healthy', () => {
    expect(toSystemLoad(healthy).level).toBe('ok');
  });

  it('is unavailable when the gateway reports itself unhealthy', () => {
    expect(toSystemLoad({ ...healthy, overall_healthy: false }).level).toBe('unavailable');
  });

  it.each(['minimal', 'offline'])('is unavailable in %s service mode', (service_mode) => {
    expect(toSystemLoad(withSummary({ service_mode })).level).toBe('unavailable');
  });

  it('is unavailable when a GPU is critical', () => {
    expect(toSystemLoad(withSummary({ gpu: { critical_devices: 1 } })).level).toBe('unavailable');
  });

  it('is unavailable when a circuit is open', () => {
    expect(toSystemLoad(withSummary({ circuit_states: { asr: 'open', tts: 'closed' } })).level).toBe(
      'unavailable'
    );
  });

  it('is delayed in degraded service mode', () => {
    expect(toSystemLoad(withSummary({ service_mode: 'degraded' })).level).toBe('delayed');
  });

  it('is delayed when a GPU warns', () => {
    expect(toSystemLoad(withSummary({ gpu: { warning_devices: 2 } })).level).toBe('delayed');
  });

  it('is delayed when the GPU asks to scale up', () => {
    expect(toSystemLoad(withSummary({ gpu: { recommended_action: 'scale_up' } })).level).toBe(
      'delayed'
    );
  });

  it('is delayed when a circuit is half open', () => {
    expect(toSystemLoad(withSummary({ circuit_states: { asr: 'half_open' } })).level).toBe(
      'delayed'
    );
  });

  it('prefers unavailable over delayed when both apply', () => {
    expect(
      toSystemLoad(
        withSummary({ service_mode: 'degraded', gpu: { critical_devices: 1, warning_devices: 3 } })
      ).level
    ).toBe('unavailable');
  });

  it('is unknown for an empty payload rather than green by default', () => {
    expect(toSystemLoad({}).level).toBe('unknown');
  });

  it('tolerates a payload with no gpu or circuit fields at all', () => {
    expect(toSystemLoad({ overall_healthy: true, summary: {} }).level).toBe('ok');
  });
  // Captured from the running gateway on 2026-08-26 via
  // GET http://127.0.0.1:8000/api/health/summary. Invented fixtures prove the
  // rules; this proves the field names.
  it('reads the real gateway response', () => {
    const live: HealthSummaryDto = {
      overall_healthy: true,
      summary: {
        service_mode: 'full',
        circuit_states: { asr: 'closed', translation: 'closed', tts: 'closed' },
        gpu: {
          critical_devices: 0,
          warning_devices: 0,
          recommended_action: 'steady',
        },
      },
    };
    expect(toSystemLoad(live).level).toBe('ok');
  });
});
