import type { PaperDevice, PaperDeviceHolder } from './ceremony-crypto.port';

/** In memory only: a reload loses the device key, and the ceremony must then start again. */
export function createPaperDeviceHolder(): PaperDeviceHolder {
  let device: PaperDevice | null = null;
  return {
    current: () => device,
    hold(next) {
      device = next;
    },
    clear() {
      device = null;
    },
  };
}
