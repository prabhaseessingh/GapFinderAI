import {redirect} from '@/i18n/navigation';
import {isAppLocale} from '@/i18n/config';

export default async function WorkspaceIndex({params}: {params: Promise<{locale: string; workspaceId: string}>}) {
  const {locale, workspaceId} = await params;
  redirect({href: `/app/w/${workspaceId}/materials`, locale: isAppLocale(locale) ? locale : 'en'});
}
