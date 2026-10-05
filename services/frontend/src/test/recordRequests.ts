import { onTestFinished } from 'vitest';
import { server } from './setup';

/**
 * Records the URL of every matching request until the current test ends.
 * Removes only its own listener: clearing them all would switch off the
 * in-flight guard in setup.ts.
 */
export function recordRequests(matches: (request: Request) => boolean): string[] {
  const urls: string[] = [];
  const listener = ({ request }: { request: Request }) => {
    if (matches(request)) {
      urls.push(request.url);
    }
  };
  server.events.on('request:start', listener);
  onTestFinished(() => server.events.removeListener('request:start', listener));
  return urls;
}
