export interface FakeClipboard {
  /** Everything written, in order. */
  written: string[];
}

/**
 * jsdom ships no clipboard, and the real one is unavailable outside a secure
 * context, so both the success and the refusal path need installing by hand.
 * `configurable` matters: each test replaces the previous definition.
 */
export function installFakeClipboard(options: { fail?: boolean } = {}): FakeClipboard {
  const written: string[] = [];

  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {
      writeText: async (text: string) => {
        if (options.fail === true) {
          throw new Error('clipboard unavailable');
        }
        written.push(text);
      },
    },
  });

  return { written };
}
