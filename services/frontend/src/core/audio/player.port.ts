/**
 * One-clip-at-a-time playback, behind a port so the queue can be tested without
 * real audio — jsdom implements no Web Audio and no timing.
 */
export interface AudioPlayerPort {
  /** Always starts from the beginning, including for the clip already loaded. */
  play(url: string): Promise<void>;
  /** Holds the playhead where it is, so `resume` carries on from there. */
  pause(): void;
  resume(): Promise<void>;
  stop(): void;
  /** Each returns an unsubscribe function. */
  onProgress(handler: (fraction: number) => void): () => void;
  onEnded(handler: () => void): () => void;
  onError(handler: () => void): () => void;
}
