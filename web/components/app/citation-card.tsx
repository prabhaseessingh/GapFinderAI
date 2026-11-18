'use client';

import {FileSearch} from 'lucide-react';
import {useTranslations} from 'next-intl';
import {Link} from '@/i18n/navigation';
import type {Citation} from '@/lib/api';
import {languageName} from './shared';

/** One cited original-language quote with a deep link into the extracted source text. */
export function CitationCard({citation, workspaceId}: {citation: Citation; workspaceId: string}) {
  const t = useTranslations('Quiz');
  const tc = useTranslations('Common');
  const tl = useTranslations('Locale');
  return (
    <div className="rounded-sm bg-pink-50 px-3 py-2 text-sm">
      <p className="text-xs font-semibold text-plum">
        {citation.document_name}{citation.page_start ? ` · ${tc('page', {page: citation.page_start})}` : ''} · {languageName(citation.source_language, tl)}
      </p>
      <p lang={citation.source_language} className="mt-1 text-ink">“{citation.original_quote}”</p>
      <Link href={`/app/w/${workspaceId}/sources/${citation.document_id}#chunk-${citation.chunk_id}`} className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-brand hover:underline">
        <FileSearch className="size-3.5" />{t('openSource')}
      </Link>
    </div>
  );
}
