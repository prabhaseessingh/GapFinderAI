'use client';

import {ArrowLeft, ExternalLink} from 'lucide-react';
import {useTranslations} from 'next-intl';
import {useEffect, useState} from 'react';
import {Button} from '@/components/ui/button';
import {Alert, Badge, Card, Skeleton} from '@/components/ui/primitives';
import {Link} from '@/i18n/navigation';
import {api, type SourceChunk} from '@/lib/api';
import {useDocumentSource} from '@/lib/queries';
import {cn} from '@/lib/utils';
import {languageName, StateBadge, useErrorText} from './shared';

function groupByPage(chunks: SourceChunk[]) {
  const pages = new Map<number | null, SourceChunk[]>();
  for (const chunk of chunks) pages.set(chunk.page_start, [...(pages.get(chunk.page_start) ?? []), chunk]);
  return [...pages.entries()];
}

export function SourceViewer({workspaceId, documentId}: {workspaceId: string; documentId: string}) {
  const t = useTranslations('Source');
  const tc = useTranslations('Common');
  const tm = useTranslations('Materials');
  const tl = useTranslations('Locale');
  const errorText = useErrorText();
  const {data, isLoading, error} = useDocumentSource(documentId);
  const [target, setTarget] = useState('');

  useEffect(() => {
    const read = () => setTarget(window.location.hash.replace('#chunk-', ''));
    read();
    window.addEventListener('hashchange', read);
    return () => window.removeEventListener('hashchange', read);
  }, []);
  useEffect(() => {
    if (target && data) document.getElementById(`chunk-${target}`)?.scrollIntoView({block: 'center'});
  }, [target, data]);

  async function openOriginal() {
    const {url} = await api<{url: string}>(`documents/${documentId}/preview-url`);
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="ghost" size="sm"><Link href={`/app/w/${workspaceId}/materials`}><ArrowLeft />{t('backToMaterials')}</Link></Button>
        {data && <Button variant="secondary" size="sm" onClick={() => void openOriginal()}><ExternalLink />{tm('openOriginal')}</Button>}
      </div>
      {isLoading && <Skeleton className="h-96" />}
      {error && <Alert tone="danger">{errorText(error)}</Alert>}
      {data && (
        <>
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-2xl">{data.document.filename}</h2>
              <StateBadge state={data.document.state} />
            </div>
            <p className="mt-1 text-sm text-muted">{t('title')} · {t('subtitle')}</p>
          </div>
          {data.chunks.length === 0 && <Alert tone="info">{t('notReady')}</Alert>}
          {groupByPage(data.chunks).map(([page, chunks]) => (
            <Card key={String(page)} className="overflow-hidden">
              <div className="flex items-center justify-between border-b border-line bg-canvas px-5 py-3">
                <h3 className="text-sm font-bold uppercase tracking-wider text-plum">{page === null ? t('noPage') : tc('page', {page})}</h3>
              </div>
              <div className="grid gap-4 p-5">
                {chunks.map((chunk) => (
                  <article
                    key={chunk.id}
                    id={`chunk-${chunk.id}`}
                    lang={chunk.source_language}
                    className={cn('scroll-mt-24 rounded-sm border-l-[3px] px-4 py-2 transition-colors', chunk.id === target ? 'border-brand bg-pink-50' : 'border-transparent')}
                  >
                    <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
                      <span className="font-semibold text-ink">{chunk.heading_path.length ? chunk.heading_path.join(' › ') : t('untitled')}</span>
                      <span>· {t('language', {language: languageName(chunk.source_language, tl)})}</span>
                      {chunk.id === target && <Badge tone="brand">{t('highlighted')}</Badge>}
                    </p>
                    <p className="mt-1.5 whitespace-pre-wrap text-[15px] text-ink">{chunk.text}</p>
                  </article>
                ))}
              </div>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}
