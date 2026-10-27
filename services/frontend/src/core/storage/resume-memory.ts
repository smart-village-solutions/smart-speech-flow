import type { ResumeMemory } from './resume-memory.port';

const STORAGE_KEY = 'ssf.staff.resumeView';

/** Session storage, read lazily; a browser that refuses it just lands on the dashboard. */
export function createResumeMemory(storage: () => Storage | null): ResumeMemory {
  return {
    remember(view) {
      try {
        storage()?.setItem(STORAGE_KEY, view);
      } catch {
        /* Storage refused: the user reopens the screen from the menu. */
      }
    },
    take() {
      try {
        const store = storage();
        const view = store?.getItem(STORAGE_KEY) ?? null;
        store?.removeItem(STORAGE_KEY);
        return view;
      } catch {
        return null;
      }
    },
  };
}
