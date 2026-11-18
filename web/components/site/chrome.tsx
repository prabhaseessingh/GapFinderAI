'use client';

import {Menu as MenuIcon, X} from 'lucide-react';
import {AnimatePresence, motion} from 'framer-motion';
import {useTranslations} from 'next-intl';
import {useEffect, useState} from 'react';
import {Logo} from '@/components/brand/logo';
import {LocaleSelect} from '@/components/app/shared';
import {Button} from '@/components/ui/button';
import {Link} from '@/i18n/navigation';
import {htmlLang, locales} from '@/i18n/config';
import {cn} from '@/lib/utils';
import {SectionLink} from './section-link';

export function SiteHeader() {
  const t = useTranslations('Nav');
  const tb = useTranslations('Brand');
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, {passive: true});
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  const links = [
    {href: '/#how' as const, label: t('how')},
    {href: '/#features' as const, label: t('features')},
    {href: '/#faq' as const, label: t('faq')}
  ];
  return (
    <header className={cn('sticky top-0 z-50 transition-[background-color,box-shadow] duration-300', scrolled || open ? 'bg-surface/95 shadow-card backdrop-blur' : 'bg-transparent')}>
      <div className="mx-auto flex h-18 max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" aria-label={tb('logoLabel')} className="flex shrink-0 items-center rounded-sm leading-none"><Logo /></Link>
        <nav aria-label="Primary" className="hidden items-center gap-1 lg:flex">
          {links.map((link) => (
            <SectionLink key={link.href} href={link.href} className="inline-flex h-11 items-center rounded-sm px-3 text-[15px] font-medium leading-none text-ink transition-colors hover:text-brand">{link.label}</SectionLink>
          ))}
        </nav>
        <div className="ml-auto hidden items-center gap-3 lg:flex [&_select]:h-11">
          <LocaleSelect />
          <Button asChild><Link href="/login">{t('signIn')}</Link></Button>
        </div>
        <Button variant="ghost" size="icon" className="ml-auto lg:hidden" aria-expanded={open} aria-controls="mobile-nav" aria-label={t('menu')} onClick={() => setOpen(!open)}>
          {open ? <X className="!size-5" /> : <MenuIcon className="!size-5" />}
        </Button>
      </div>
      <AnimatePresence>
        {open && (
          <motion.nav
            id="mobile-nav"
            aria-label="Mobile"
            initial={{height: 0, opacity: 0}}
            animate={{height: 'auto', opacity: 1}}
            exit={{height: 0, opacity: 0}}
            transition={{duration: 0.25}}
            className="overflow-hidden border-t border-line lg:hidden"
          >
            <div className="grid gap-1 px-4 py-4">
              {links.map((link) => (
                <SectionLink key={link.href} href={link.href} onClick={() => setOpen(false)} className="rounded-sm px-3 py-3 font-medium text-ink hover:bg-pink-50">{link.label}</SectionLink>
              ))}
              <LocaleSelect className="px-3 py-2" />
              <div className="mt-2 grid gap-2">
                <Button asChild><Link href="/login">{t('signIn')}</Link></Button>
              </div>
            </div>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}

export function SiteFooter() {
  const t = useTranslations('Footer');
  const tn = useTranslations('Nav');
  const tl = useTranslations('Locale');
  return (
    <footer className="bg-dark-gradient text-white/75">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[2fr_1fr_1fr_1fr]">
        <div>
          <Logo tone="light" />
          <p className="mt-4 max-w-xs text-sm">{t('tagline')}</p>
        </div>
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-white">{t('product')}</h2>
          <ul className="mt-4 grid gap-2 text-sm">
            <li><SectionLink href="/#how" className="hover:text-white">{tn('how')}</SectionLink></li>
            <li><SectionLink href="/#features" className="hover:text-white">{tn('features')}</SectionLink></li>
            <li><SectionLink href="/#faq" className="hover:text-white">{tn('faq')}</SectionLink></li>
          </ul>
        </div>
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-white">{t('languages')}</h2>
          <ul className="mt-4 grid gap-2 text-sm">
            {locales.map((locale) => (
              <li key={locale}><a href={`/${locale}`} hrefLang={htmlLang(locale)} lang={htmlLang(locale)} className="hover:text-white">{tl(locale)}</a></li>
            ))}
          </ul>
        </div>
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-white">{t('legal')}</h2>
          <ul className="mt-4 grid gap-2 text-sm">
            <li><Link href="/privacy" className="hover:text-white">{t('privacy')}</Link></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-white/10">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-5 text-xs sm:px-6">
          <p>{t('rights', {year: new Date().getFullYear()})}</p>
          <p data-testid="built-by">{t('builtBy', {name: 'Prabhasees Singh'})}</p>
        </div>
      </div>
    </footer>
  );
}
