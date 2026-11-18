import {describe, expect, it} from 'vitest';
import {IntlMessageFormat} from 'intl-messageformat';
import {locales} from '@/i18n/config';
import en from '@/messages/en.json';

type Tree = {[key: string]: string | Tree};
const flatten = (tree: Tree, prefix = ''): Record<string, string> =>
  Object.entries(tree).reduce<Record<string, string>>((acc, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === 'string' ? {...acc, [path]: value} : {...acc, ...flatten(value, path)};
  }, {});
const tokens = (message: string) => [...new Set([...message.matchAll(/\{(\w+)\s*[,}]|<(\w+)>/g)].map((m) => m[1] ?? `<${m[2]}>`))].sort();

const reference = flatten(en as Tree);

describe('locale catalogs (release gate: no missing or extra keys)', () => {
  for (const locale of locales) {
    it(`${locale} has exactly the English keys, same placeholders and valid ICU`, async () => {
      const catalog = flatten((await import(`../messages/${locale}.json`)).default as Tree);
      expect(Object.keys(catalog).sort()).toEqual(Object.keys(reference).sort());
      for (const [key, message] of Object.entries(catalog)) {
        expect(message.trim(), key).not.toBe('');
        expect(tokens(message), `${locale}:${key}`).toEqual(tokens(reference[key]));
        expect(() => new IntlMessageFormat(message, locale === 'deccani-Latn' ? 'en' : locale), `${locale}:${key}`).not.toThrow();
      }
    });
  }
});
