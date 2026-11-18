'use client';

import {CalendarDays, ClipboardCheck, FileStack, LineChart, MessageCircleQuestion, Network, Target} from 'lucide-react';
import {motion} from 'framer-motion';
import {useTranslations} from 'next-intl';
import {Alert, Badge, Skeleton} from '@/components/ui/primitives';
import {Link, usePathname} from '@/i18n/navigation';
import {useWorkspaces} from '@/lib/queries';
import {cn} from '@/lib/utils';

/** Only sections that exist are shown (no placeholder controls for future phases). */
const SECTIONS = [
  {slug: 'materials', icon: FileStack},
  {slug: 'topics', icon: Network},
  {slug: 'quiz', icon: ClipboardCheck},
  {slug: 'report', icon: Target},
  {slug: 'plan', icon: CalendarDays},
  {slug: 'progress', icon: LineChart},
  {slug: 'explain', icon: MessageCircleQuestion}
] as const;

export function WorkspaceHeader({workspaceId}: {workspaceId: string}) {
  const t = useTranslations('Workspace');
  const ta = useTranslations('App');
  const pathname = usePathname();
  const {data, isLoading} = useWorkspaces();
  const workspace = data?.find((item) => item.id === workspaceId);
  if (isLoading) return <Skeleton className="h-20" />;
  if (!workspace) return <Alert tone="warning" title={ta('notFound')} />;
  return (
    <div className="flex flex-col gap-5 border-b border-line pb-1">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl sm:text-3xl">{workspace.title}</h1>
        {workspace.demo_source && <Badge tone="info">{t('demoBadge')}</Badge>}
      </div>
      {workspace.demo_source && <p className="-mt-2 text-sm text-muted">{t('demoNotice')}</p>}
      <nav aria-label={t('tabsLabel')} className="-mb-px flex gap-1 overflow-x-auto">
        {SECTIONS.map(({slug, icon: Icon}) => {
          const href = `/app/w/${workspaceId}/${slug}`;
          const active = pathname.startsWith(href) || (slug === 'materials' && pathname.includes('/sources/'));
          return (
            <Link
              key={slug}
              href={href}
              aria-current={active ? 'page' : undefined}
              className={cn('relative flex items-center gap-2 whitespace-nowrap px-4 py-3 text-sm font-semibold transition-colors', active ? 'text-brand' : 'text-muted hover:text-ink')}
            >
              <Icon className="size-4" />
              {t(slug)}
              {active && <motion.span layoutId="workspace-tab" className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-gradient-vivid" />}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
