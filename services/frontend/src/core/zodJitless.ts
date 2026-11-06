import { z } from 'zod';

// Loaded before any schema exists: zod otherwise probes `new Function`, which a strict CSP reports (#620).
z.config({ jitless: true });
