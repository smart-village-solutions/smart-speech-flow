import { describe, expect, it } from 'vitest';
import { readConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { createLanguageRepository } from '@/domain/language/language.repository';

const client = createHttpClient(readConfig({ VITE_API_BASE_URL: 'http://api.test' }), () => 'en');
const repository = createLanguageRepository(client);

describe('language repository', () => {
  it('returns the customer-selectable languages, excluding the admin default', async () => {
    const languages = await repository.listCustomerLanguages();

    expect(languages.map((language) => language.code)).toEqual([
      'en',
      'ar',
      'tr',
      'ru',
      'uk',
      'am',
      'ti',
      'ku',
      'fa',
    ]);
    expect(languages).not.toContainEqual(expect.objectContaining({ code: 'de' }));
  });

  it('maps native and English names onto the domain model', async () => {
    const languages = await repository.listCustomerLanguages();
    const arabic = languages.find((language) => language.code === 'ar');

    expect(arabic).toEqual({ code: 'ar', native: 'العربية', english: 'Arabic' });
  });
});
