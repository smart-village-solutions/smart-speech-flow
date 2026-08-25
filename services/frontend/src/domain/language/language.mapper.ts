import type { Language } from './language.types';

export interface SupportedLanguagesDto {
  languages: Record<string, { name: string; native: string }>;
  admin_default: string;
  popular: string[];
}

/** The agent's own language (`admin_default`) is never a customer choice. */
export function toCustomerLanguages(dto: SupportedLanguagesDto): Language[] {
  return Object.entries(dto.languages)
    .filter(([code]) => code !== dto.admin_default)
    .map(([code, names]) => ({ code, native: names.native, english: names.name }));
}
