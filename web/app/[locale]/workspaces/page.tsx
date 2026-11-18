import {redirect} from '@/i18n/navigation';
import {isAppLocale} from '@/i18n/config';

/** Legacy route kept working: the workspace UI now lives at /app. */
export default async function LegacyWorkspaces({params}: {params: Promise<{locale: string}>}) {
  const {locale} = await params;
  redirect({href: '/app', locale: isAppLocale(locale) ? locale : 'en'});
}
