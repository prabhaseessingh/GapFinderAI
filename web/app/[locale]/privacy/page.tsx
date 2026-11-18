import {getTranslations, setRequestLocale} from 'next-intl/server';
import {SiteFooter, SiteHeader} from '@/components/site/chrome';
import {PRIVACY_POLICY_VERSION} from '@/lib/privacy';

const SECTIONS = ['s1', 's2', 's3', 's4', 's5', 's6', 's7'] as const;

export default async function PrivacyPage({params}: {params: Promise<{locale: string}>}) {
  setRequestLocale((await params).locale);
  const t = await getTranslations('Privacy');
  return (
    <>
      <SiteHeader />
      <main id="main" className="mx-auto max-w-3xl px-4 py-14 sm:px-6 sm:py-20">
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-brand">{t('version', {version: PRIVACY_POLICY_VERSION})}</p>
        <h1 className="mt-3 text-4xl sm:text-5xl">{t('title')}</h1>
        <p className="mt-6 text-lg">{t('intro')}</p>
        <div className="mt-10 grid gap-8">
          {SECTIONS.map((key, index) => (
            <section key={key} aria-labelledby={key}>
              <h2 id={key} className="flex items-center gap-3 text-xl">
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-pink-100 text-sm text-brand">{index + 1}</span>
                {t(`${key}Title`)}
              </h2>
              <p className="mt-3 pl-11">{t(`${key}Body`)}</p>
            </section>
          ))}
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
