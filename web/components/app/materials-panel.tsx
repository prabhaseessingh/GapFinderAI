'use client';

import {BookOpen, ExternalLink, FileQuestion, FileText, NotebookPen, RotateCw, ScrollText, Trash2, UploadCloud} from 'lucide-react';
import {AnimatePresence, motion} from 'framer-motion';
import {useFormatter, useLocale, useNow, useTranslations} from 'next-intl';
import {useRef, useState, type DragEvent} from 'react';
import * as tus from 'tus-js-client';
import {Button} from '@/components/ui/button';
import {Alert, Card, Progress, Skeleton} from '@/components/ui/primitives';
import {Link} from '@/i18n/navigation';
import {api, ApiError, type MaterialRole, type StudyDocument, type UploadIntent} from '@/lib/api';
import {keys, useApiMutation, useDocuments} from '@/lib/queries';
import {createSupabaseBrowserClient} from '@/lib/supabase/browser';
import {cn, formatBytes} from '@/lib/utils';
import {ConfirmDialog} from './dashboard';
import {PipelineSteps, StateBadge, useErrorText} from './shared';

export const ROLES: {role: MaterialRole; icon: typeof BookOpen}[] = [
  {role: 'syllabus', icon: ScrollText},
  {role: 'textbook', icon: BookOpen},
  {role: 'notes', icon: NotebookPen},
  {role: 'past_paper', icon: FileQuestion}
];
const MIME_BY_EXTENSION: Record<string, string> = {
  txt: 'text/plain',
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
};
export const MAX_BYTES = 50 * 1024 * 1024; // Supabase Free per-file limit; no lower app limit.

export function mimeFor(file: File): string | null {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  return MIME_BY_EXTENSION[extension] ?? null;
}

async function sha256(file: File) {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

type UploadState = {name: string; percent: number | null} | null;

function DocumentRow({document, workspaceId}: {document: StudyDocument; workspaceId: string}) {
  const t = useTranslations('Materials');
  const tf = useTranslations('Failures');
  const tc = useTranslations('Common');
  const locale = useLocale();
  const errorText = useErrorText();
  const format = useFormatter();
  const now = useNow({updateInterval: 60_000});
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState('');
  const Icon = ROLES.find((item) => item.role === document.material_role)?.icon ?? FileText;
  const retry = useApiMutation(() => api(`documents/${document.id}/retry-processing`, {method: 'POST'}), () => [keys.documents(workspaceId)]);
  const remove = useApiMutation(() => api(`documents/${document.id}`, {method: 'DELETE'}), () => [keys.documents(workspaceId), keys.topics(workspaceId), keys.questions(workspaceId)]);
  async function openOriginal() {
    try {
      const {url} = await api<{url: string}>(`documents/${document.id}/preview-url`);
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (error) {
      setMessage(errorText(error));
    }
  }
  return (
    <motion.li layout initial={{opacity: 0, y: 8}} animate={{opacity: 1, y: 0}} exit={{opacity: 0, x: -20}} className="rounded-md border border-line bg-surface p-4 transition-shadow hover:shadow-card">
      <div className="flex flex-wrap items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-sm bg-pink-100 text-brand"><Icon className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-ink" title={document.filename}>{document.filename}</p>
          <p className="text-xs text-muted">
            {t(`roles.${document.material_role}`)} · {formatBytes(document.byte_size, locale)}
            {document.page_count ? ` · ${tc('pages', {count: document.page_count})}` : ''} · {format.relativeTime(new Date(document.created_at), now)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <PipelineSteps state={document.state} />
          <StateBadge state={document.state} />
        </div>
      </div>
      {document.state === 'failed' && (
        <Alert tone="danger" className="mt-3" action={<Button size="sm" variant="secondary" disabled={retry.isPending} onClick={() => retry.mutate(undefined, {onError: (e) => setMessage(errorText(e))})}><RotateCw />{t('retry')}</Button>}>
          {document.failure_code && tf.has(document.failure_code) ? tf(document.failure_code as 'fallback') : tf('fallback')}
          {document.processing_attempts > 0 && <span className="ml-1 text-muted">({t('attempts', {count: document.processing_attempts})})</span>}
        </Alert>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {document.state === 'ready' || document.state === 'mapping' ? (
          <Button asChild size="sm" variant="soft"><Link href={`/app/w/${workspaceId}/sources/${document.id}`}><ScrollText />{t('openSource')}</Link></Button>
        ) : null}
        {document.state !== 'uploaded' && <Button size="sm" variant="ghost" onClick={openOriginal}><ExternalLink />{t('openOriginal')}</Button>}
        <Button size="sm" variant="ghost" className="text-danger hover:bg-danger-50 hover:text-danger" onClick={() => setConfirming(true)}><Trash2 />{tc('delete')}</Button>
      </div>
      {message && <p role="alert" className="mt-2 text-sm text-danger">{message}</p>}
      <ConfirmDialog open={confirming} onOpenChange={setConfirming} title={t('deleteTitle', {name: document.filename})} body={t('deleteBody')} confirmLabel={tc('delete')} onConfirm={() => remove.mutateAsync(undefined)} />
    </motion.li>
  );
}

export function MaterialsPanel({workspaceId}: {workspaceId: string}) {
  const t = useTranslations('Materials');
  const errorText = useErrorText();
  const {data: documents, isLoading, refetch} = useDocuments(workspaceId);
  const [role, setRole] = useState<MaterialRole>('syllabus');
  const [upload, setUpload] = useState<UploadState>(null);
  const [status, setStatus] = useState<{tone: 'success' | 'danger'; text: string} | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function start(file: File) {
    setStatus(null);
    const mime = mimeFor(file);
    if (!mime) return setStatus({tone: 'danger', text: t('unsupported')});
    if (file.size > MAX_BYTES) return setStatus({tone: 'danger', text: t('tooLarge')});
    setUpload({name: file.name, percent: null});
    try {
      const checksum = await sha256(file);
      const intent = await api<UploadIntent>('documents/upload-intent', {
        method: 'POST',
        body: {workspace_id: workspaceId, material_role: role, filename: file.name, mime_type: mime, byte_size: file.size, checksum_sha256: checksum}
      });
      const {data: {session}} = await createSupabaseBrowserClient().auth.getSession();
      const apikey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
      if (!session || !apikey) throw new ApiError(401, 'UNAUTHENTICATED', 'Session expired');
      await new Promise<void>((resolve, reject) => {
        new tus.Upload(file, {
          endpoint: intent.tus_endpoint,
          chunkSize: 6 * 1024 * 1024, // Supabase requires 6 MB chunks for resumable uploads
          retryDelays: [0, 3000, 5000, 10000],
          headers: {authorization: `Bearer ${session.access_token}`, apikey, 'x-upsert': 'false'},
          uploadDataDuringCreation: true,
          removeFingerprintOnSuccess: true,
          metadata: {bucketName: intent.bucket, objectName: intent.storage_path, contentType: mime},
          onError: reject,
          onSuccess: () => resolve(),
          onProgress: (sent, total) => setUpload({name: file.name, percent: Math.round((sent / total) * 100)})
        }).start();
      });
      await api(`documents/${intent.document_id}/confirm`, {method: 'POST', body: {checksum_sha256: checksum}});
      setStatus({tone: 'success', text: t('uploaded', {name: file.name})});
      await refetch();
    } catch (error) {
      setStatus({tone: 'danger', text: errorText(error)});
    } finally {
      setUpload(null);
      if (input.current) input.current.value = '';
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file && !upload) void start(file);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <Card className="h-fit p-5 sm:p-6">
        <h2 className="text-xl">{t('title')}</h2>
        <p className="mt-1 text-sm text-muted">{t('subtitle')}</p>
        <fieldset className="mt-5">
          <legend className="text-sm font-semibold text-ink">{t('role')}</legend>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {ROLES.map(({role: value, icon: Icon}) => (
              <label key={value} className={cn('flex cursor-pointer items-center gap-2 rounded-sm border px-3 py-2.5 text-sm font-semibold transition-colors has-[:focus-visible]:ring-4 has-[:focus-visible]:ring-brand/20', role === value ? 'border-brand bg-pink-50 text-brand' : 'border-line text-ink hover:border-line-strong')}>
                <input type="radio" name="role" value={value} checked={role === value} onChange={() => setRole(value)} className="sr-only" />
                <Icon className="size-4 shrink-0" />{t(`roles.${value}`)}
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">{t(`roleHints.${role}`)}</p>
        </fieldset>
        <div
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn('mt-5 grid place-items-center rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors', dragging ? 'border-brand bg-pink-50' : 'border-line-strong bg-canvas')}
        >
          <UploadCloud className={cn('size-9 transition-colors', dragging ? 'text-brand' : 'text-plum')} aria-hidden />
          <p className="mt-3 text-sm font-semibold text-ink">
            {t.rich('drop', {
              browse: (chunks) => (
                <button type="button" disabled={Boolean(upload)} onClick={() => input.current?.click()} className="text-brand underline underline-offset-4 disabled:opacity-50">{chunks}</button>
              )
            })}
          </p>
          <p className="mt-1 text-xs text-muted">{t('dropHint')}</p>
          <input ref={input} type="file" className="sr-only" tabIndex={-1} aria-label={t('role')} accept=".txt,.pdf,.docx" onChange={(event) => { const file = event.target.files?.[0]; if (file) void start(file); }} />
        </div>
        <div aria-live="polite" className="mt-4 grid gap-2">
          {upload && (
            <>
              <p className="text-sm font-medium text-ink">{upload.percent === null ? t('preparing', {name: upload.name}) : t('uploading', {name: upload.name, percent: upload.percent})}</p>
              <Progress value={upload.percent ?? 4} label={upload.name} />
            </>
          )}
          {status && <Alert tone={status.tone}>{status.text}</Alert>}
        </div>
      </Card>
      <section aria-labelledby="files-heading">
        <h2 id="files-heading" className="text-xl">{t('listTitle')}</h2>
        <div className="mt-4">
          {isLoading && <div className="grid gap-3">{[0, 1].map((i) => <Skeleton key={i} className="h-28" />)}</div>}
          {documents?.length === 0 && <Card className="p-8 text-center text-muted">{t('empty')}</Card>}
          <ul className="grid gap-3">
            <AnimatePresence initial={false}>
              {documents?.map((document) => <DocumentRow key={document.id} document={document} workspaceId={workspaceId} />)}
            </AnimatePresence>
          </ul>
        </div>
      </section>
    </div>
  );
}
