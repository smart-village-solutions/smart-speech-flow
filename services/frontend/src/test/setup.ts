import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);

// A response that lands after its file's jsdom is torn down throws outside any
// test ("ProgressEvent is not defined"), and only on a slow enough runner. So a
// test whose request handler has not returned yet fails, on every machine. The
// delivery that follows the handler is all microtasks and cannot outlast the
// file: Vitest only reaches teardown through a macrotask.
const inFlight = new Map<string, string>();
const track = ({ request, requestId }: { request: Request; requestId: string }) => {
  inFlight.set(requestId, `${request.method} ${new URL(request.url).pathname}`);
};
const settle = ({ requestId }: { requestId: string }) => inFlight.delete(requestId);
// Under onUnhandledRequest: 'error' an unhandled request never emits request:end,
// and neither does a throwing handler.
const SETTLED = ['request:end', 'request:unhandled', 'unhandledException'] as const;

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
// Per test, so a file that clears every listener cannot switch the guard off.
beforeEach(() => {
  server.events.on('request:start', track);
  for (const event of SETTLED) server.events.on(event, settle);
});
afterEach(() => {
  server.events.removeListener('request:start', track);
  for (const event of SETTLED) server.events.removeListener(event, settle);
  server.resetHandlers();
  const pending = [...inFlight.values()];
  inFlight.clear();
  if (pending.length > 0) {
    throw new Error(`Request still in flight when the test ended: ${pending.join(', ')}`);
  }
});
afterAll(() => server.close());

// jsdom implements neither of these, and the conversation screen uses both.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
      addListener: () => {},
      removeListener: () => {},
    }) as unknown as MediaQueryList;
}

if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}

// jsdom implements no media element at all. Screens are given a fake player;
// this covers the provider tests that exercise the real composition root.
HTMLMediaElement.prototype.play = () => Promise.resolve();
HTMLMediaElement.prototype.pause = () => {};
