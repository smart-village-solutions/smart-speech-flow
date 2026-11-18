import { createContext } from 'react';
/** Only the permitted task reference and filter choices survive a requested MFA redirect. */
export const TaskStepUpReturn = createContext<string | null>(null);
export const UnlockSigningVersion = createContext<((version: number) => void) | null>(null);
