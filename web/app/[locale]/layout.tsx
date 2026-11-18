import type {Metadata} from 'next';
import {Noto_Sans_Gurmukhi, Noto_Sans_Telugu, Poppins} from 'next/font/google';
import {notFound} from 'next/navigation';
import {NextIntlClientProvider} from 'next-intl';
import {getMessages, getTranslations, setRequestLocale} from 'next-intl/server';
import type {ReactNode} from 'react';
import {Providers} from '@/components/providers';
import {htmlLang, isAppLocale, locales} from '@/i18n/config';
import '../globals.css';

// Poppins is iGebra's typeface (Latin + Devanagari); Noto covers Gurmukhi and Telugu.
const poppins = Poppins({subsets: ['latin', 'devanagari'], weight: ['400', '500', '600', '700', '800'], variable: '--font-poppins', display: 'swap'});
const gurmukhi = Noto_Sans_Gurmukhi({subsets: ['gurmukhi'], weight: ['400', '600', '700'], variable: '--font-gurmukhi', display: 'swap'});
const telugu = Noto_Sans_Telugu({subsets: ['telugu'], weight: ['400', '600', '700'], variable: '--font-telugu', display: 'swap'});

export function generateStaticParams() {
  return locales.map((locale) => ({locale}));
}

export async function generateMetadata({params}: {params: Promise<{locale: string}>}): Promise<Metadata> {
  const {locale} = await params;
  const t = await getTranslations({locale: isAppLocale(locale) ? locale : 'en', namespace: 'Meta'});
  return {title: t('title'), description: t('description'), icons: {icon: '/icon.svg'}};
}

export default async function LocaleLayout({children, params}: {children: ReactNode; params: Promise<{locale: string}>}) {
  const {locale} = await params;
  if (!isAppLocale(locale)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations('Common');
  return (
    <html lang={htmlLang(locale)} className={`${poppins.variable} ${gurmukhi.variable} ${telugu.variable}`}>
      <body>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-sm focus:bg-ink focus:px-4 focus:py-2 focus:text-white">
          {t('skipToContent')}
        </a>
        <NextIntlClientProvider messages={await getMessages()}>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
