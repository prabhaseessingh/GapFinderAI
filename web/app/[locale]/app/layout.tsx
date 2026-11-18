import type {ReactNode} from 'react';
import {setRequestLocale} from 'next-intl/server';
import {AppShell} from '@/components/app/app-shell';
import {redirect} from '@/i18n/navigation';
import {isAppLocale, type AppLocale} from '@/i18n/config';
import {createSupabaseServerClient} from '@/lib/supabase/server';

export default async function AppLayout({children, params}: {children: ReactNode; params: Promise<{locale: string}>}) {
  const {locale: raw} = await params;
  const locale: AppLocale = isAppLocale(raw) ? raw : 'en';
  setRequestLocale(locale);
  const supabase = await createSupabaseServerClient();
  const {data} = await supabase.auth.getUser();
  if (!data.user) redirect({href: '/login', locale});
  return <AppShell email={data.user?.email ?? ''}>{children}</AppShell>;
}
