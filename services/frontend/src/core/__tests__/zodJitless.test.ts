import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, it } from 'vitest';
import { z } from 'zod';
import '../zodJitless';

it("turns off zod's eval probe", () => {
  expect(z.config().jitless).toBe(true);
});

it('is the first module main.tsx loads, before any schema is built', () => {
  const main = readFileSync(path.join(import.meta.dirname, '..', '..', 'main.tsx'), 'utf8');
  expect(/^import .+$/m.exec(main)?.[0]).toBe("import './core/zodJitless'");
});
