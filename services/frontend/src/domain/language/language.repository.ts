import type { AxiosInstance } from 'axios';
import { toCustomerLanguages } from './language.mapper';
import type { SupportedLanguagesDto } from './language.mapper';
import type { Language } from './language.types';

export interface LanguageRepository {
  listCustomerLanguages(): Promise<Language[]>;
}

export function createLanguageRepository(http: AxiosInstance): LanguageRepository {
  return {
    async listCustomerLanguages() {
      const response = await http.get<SupportedLanguagesDto>('/api/languages/supported');
      return toCustomerLanguages(response.data);
    },
  };
}
