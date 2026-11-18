export const locales = ['en', 'hi-IN', 'pa-IN', 'te-IN', 'deccani-Latn'] as const;
export type AppLocale = (typeof locales)[number];
export const defaultLocale: AppLocale = 'en';
export const isAppLocale = (value: string): value is AppLocale => locales.includes(value as AppLocale);


/** BCP-47 tag for lang/hreflang attributes. Dakhni's ISO 639-3 code is 'dcc'; routes keep 'deccani-Latn'. */
export const htmlLang = (locale: string) => (locale === 'deccani-Latn' ? 'dcc-Latn' : locale);
