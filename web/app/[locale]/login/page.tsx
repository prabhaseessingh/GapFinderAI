import {CheckCircle2} from 'lucide-react';
import {getTranslations, setRequestLocale} from 'next-intl/server';
import {Suspense} from 'react';
import {Logo} from '@/components/brand/logo';
import {LocaleSelect} from '@/components/app/shared';
import {LoginForm} from '@/components/login-form';
import {Link} from '@/i18n/navigation';

export default async function LoginPage({params}: {params: Promise<{locale: string}>}) {
  setRequestLocale((await params).locale);
  const t = await getTranslations('Auth');
  const th = await getTranslations('Home');
  const tb = await getTranslations('Brand');
  return (
    <div className="grid min-h-dvh grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden overflow-hidden bg-dark-gradient p-12 text-white lg:flex lg:flex-col">
        <Link href="/" aria-label={tb('logoLabel')} className="w-fit rounded-sm"><Logo tone="light" /></Link>
        <div className="mt-auto max-w-md">
          <h2 className="text-4xl text-white">{t('sideTitle')}</h2>
          <p className="mt-4 text-white/75">{t('sideBody')}</p>
          <ul className="mt-8 grid gap-3 text-sm">
            {[th('trust1'), th('trust2'), th('trust3')].map((item) => (
              <li key={item} className="flex items-center gap-3"><CheckCircle2 className="size-5 text-amber" />{item}</li>
            ))}
          </ul>
        </div>
        <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 size-80 rounded-full bg-brand/30 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-32 left-10 size-72 rounded-full bg-amber/20 blur-3xl" />
      </aside>
      <main id="main" className="flex flex-col px-4 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <Link href="/" aria-label={tb('logoLabel')} className="rounded-sm lg:invisible"><Logo /></Link>
          <LocaleSelect />
        </div>
        <div className="flex flex-1 items-center justify-center py-10">
          <Suspense><LoginForm /></Suspense>
        </div>
      </main>
    </div>
  );
}
