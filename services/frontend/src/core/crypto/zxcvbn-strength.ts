import type { PassphraseStrength } from './archive-crypto.port';

type Check = (passphrase: string, userInputs: string[]) => number;

/** The dictionaries are large, so they load on first use rather than with the app. */
async function loadCheck(): Promise<Check> {
  const [{ ZxcvbnFactory }, common, de, en] = await Promise.all([
    import('@zxcvbn-ts/core'),
    import('@zxcvbn-ts/language-common'),
    import('@zxcvbn-ts/language-de'),
    import('@zxcvbn-ts/language-en'),
  ]);
  const factory = new ZxcvbnFactory({
    dictionary: { ...common.dictionary, ...de.dictionary, ...en.dictionary },
    graphs: common.adjacencyGraphs,
    translations: en.translations,
  });
  return (passphrase, userInputs) => factory.check(passphrase, userInputs).score;
}

export function createZxcvbnStrength(): PassphraseStrength {
  let check: Promise<Check> | null = null;
  return {
    async score(passphrase, userInputs) {
      check ??= loadCheck();
      return (await check)(passphrase, [...userInputs]);
    },
  };
}
