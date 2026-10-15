import type { SystemLoad } from './health.types';

/**
 * Every field is optional: the gateway builds this payload with `.get(…, default)`
 * throughout (`api_gateway/routes/circuit_breaker.py:351`), so absence is normal
 * rather than exceptional.
 */
export interface HealthSummaryDto {
  overall_healthy?: boolean;
  summary?: {
    service_mode?: string;
    circuit_states?: Record<string, string>;
    gpu?: {
      critical_devices?: number;
      warning_devices?: number;
      recommended_action?: string;
    };
  };
  gpu_summary?: {
    autoscaling_signals?: {
      service?: string;
      recommended_action?: string;
      reasons?: string[];
    }[];
  };
}

const DOWN_MODES = new Set(['minimal', 'offline']);

/**
 * The speech services ask to scale up once GPU memory reaches 85%
 * (`services/resource_metrics.py`), but their models stay resident, so the card
 * sits above that with nobody talking. Memory that is actually running out
 * still turns the light yellow through the gateway's own warning level (94%).
 */
const RESIDENT_GPU_MEMORY = /^gpu\d+_mem>=/;

function asksToScaleForLoad(dto: HealthSummaryDto): boolean {
  if (dto.summary?.gpu?.recommended_action !== 'scale_up') {
    return false;
  }
  const signals = dto.gpu_summary?.autoscaling_signals;
  if (!signals) {
    return true;
  }
  return signals
    .filter((signal) => signal.recommended_action === 'scale_up')
    .some((signal) => (signal.reasons ?? []).some((reason) => !RESIDENT_GPU_MEMORY.test(reason)));
}

function isUnavailable(dto: HealthSummaryDto, circuits: string[]): boolean {
  const { service_mode: mode, gpu } = dto.summary ?? {};

  return (
    dto.overall_healthy === false ||
    DOWN_MODES.has(mode ?? '') ||
    (gpu?.critical_devices ?? 0) > 0 ||
    circuits.includes('open')
  );
}

function isDelayed(dto: HealthSummaryDto, circuits: string[]): boolean {
  const { service_mode: mode, gpu } = dto.summary ?? {};

  return (
    mode === 'degraded' ||
    (gpu?.warning_devices ?? 0) > 0 ||
    asksToScaleForLoad(dto) ||
    circuits.includes('half_open')
  );
}

export function toSystemLoad(dto: HealthSummaryDto): SystemLoad {
  if (dto.overall_healthy === undefined && dto.summary === undefined) {
    return { level: 'unknown' };
  }

  const circuits = Object.values(dto.summary?.circuit_states ?? {});

  if (isUnavailable(dto, circuits)) {
    return { level: 'unavailable' };
  }
  return { level: isDelayed(dto, circuits) ? 'delayed' : 'ok' };
}
