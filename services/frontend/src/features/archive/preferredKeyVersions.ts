import { createContext } from 'react';

/** The ordinary archive viewer's choice, including audited reopens for audio and amendments. */
export const PreferredKeyVersions = createContext<readonly number[] | undefined>(undefined);
