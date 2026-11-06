import { writeFileSync } from 'node:fs';
import { securityHeaders } from './securityPolicy.ts';

// Run by the Dockerfile before `npm run build`, from the same build values the bundle is compiled with.
const [target] = process.argv.slice(2);
if (!target) throw new Error('usage: node security/writeSecurityHeaders.ts <output file>');
writeFileSync(target, securityHeaders(process.env, true).include);
