'use client';

import {CheckCheck, FileSearch, Loader2, MessageCircleQuestion, MoreHorizontal, Pencil, Plus, RotateCcw, Trash2, Undo2, CheckCircle2} from 'lucide-react';
import {useLocale, useTranslations} from 'next-intl';
import {useState, type FormEvent} from 'react';
import {Button} from '@/components/ui/button';
import {Alert, Badge, Card, Dialog, DialogContent, Input, Label, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Select, Skeleton} from '@/components/ui/primitives';
import {Link, useRouter} from '@/i18n/navigation';
import {htmlLang, type AppLocale} from '@/i18n/config';
import {api, type JobStatus, type Topic} from '@/lib/api';
import {keys, useApiMutation, useCitations, useDocuments, useJob, usePastPaperQuestions, useTopics} from '@/lib/queries';
import {ConfirmDialog} from './dashboard';
import {explainHref} from './explain-link';
import {languageName, useErrorText} from './shared';
import {TopicTree} from './topic-tree';

function JobBanner({job, status}: {job: 'propose' | 'map_past_papers' | 'segment_past_paper'; status?: JobStatus}) {
  const t = useTranslations('Jobs');
  const [sawActive, setSawActive] = useState(false);
  const active = status?.state === 'queued' || status?.state === 'running';
  if (active && !sawActive) setSawActive(true); // render-time state adjustment (React docs pattern)
  if (!status || status.state === 'none') return null;
  // Success is announced only for runs this session watched; old runs stay quiet.
  if (status.state === 'succeeded' && !sawActive) return null;
  const reasonKey = status.error_code?.startsWith('AI_OUTPUT_REJECTED') ? 'rejected' : status.error_code ?? 'fallback';
  const tone = status.state === 'failed' ? 'danger' : status.state === 'succeeded' ? 'success' : 'info';
  return (
    <Alert tone={tone} title={<span className="inline-flex items-center gap-2">{['queued', 'running'].includes(status.state) && <Loader2 className="size-4 animate-spin" />}{t(`${job}.${status.state}` as 'propose.queued')}</span>}>
      {status.state === 'failed' && (t.has(`reasons.${reasonKey}`) ? t(`reasons.${reasonKey}` as 'reasons.fallback') : t('reasons.fallback'))}
    </Alert>
  );
}

function EvidenceDrawer({topic, onClose, workspaceId}: {topic: Topic | null; onClose: () => void; workspaceId: string}) {
  const t = useTranslations('Topics');
  const tc = useTranslations('Common');
  const tl = useTranslations('Locale');
  const locale = useLocale() as AppLocale;
  const {data, isLoading, error, translating} = useCitations(topic?.id ?? null, locale);
  const errorText = useErrorText();
  return (
    <Dialog open={Boolean(topic)} onOpenChange={(open) => !open && onClose()}>
      {topic && (
        <DialogContent side="right" title={t('evidenceTitle', {title: topic.title})} description={t('evidenceSubtitle')} closeLabel={tc('close')}>
          {isLoading && <div className="grid gap-3">{[0, 1].map((i) => <Skeleton key={i} className="h-32" />)}</div>}
          {error && <Alert tone="danger">{errorText(error)}</Alert>}
          {data?.length === 0 && <p className="text-muted">{t('noEvidence')}</p>}
          {translating && <p role="status" className="mb-3 inline-flex items-center gap-2 text-xs text-muted"><Loader2 className="size-3.5 animate-spin" />{t('translating')}</p>}
          <ol className="grid gap-4">
            {data?.map((citation, index) => (
              <li key={`${citation.chunk_id}-${index}`} className="rounded-md border border-line p-4">
                <p className="flex flex-wrap items-center gap-2 text-xs font-semibold text-muted">
                  <Badge tone="brand">{citation.document_name}</Badge>
                  {citation.page_start ? <span>{tc('page', {page: citation.page_start})}</span> : null}
                  {citation.heading_path.length > 0 && <span className="truncate">· {citation.heading_path.join(' › ')}</span>}
                </p>
                <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-plum">{t('originalQuote', {language: languageName(citation.source_language, tl)})}</p>
                <blockquote lang={citation.source_language} className="mt-1 border-l-[3px] border-brand bg-pink-50 px-3 py-2 text-[15px] text-ink">“{citation.original_quote}”</blockquote>
                {citation.translated_quote && (
                  <>
                    <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">{t('translation', {language: tl(locale)})}</p>
                    <p lang={htmlLang(locale)} className="mt-1 border-l-[3px] border-line-strong px-3 py-1 text-sm text-text">{citation.translated_quote}</p>
                  </>
                )}
                <Link href={`/app/w/${workspaceId}/sources/${citation.document_id}#chunk-${citation.chunk_id}`} className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand underline-offset-4 hover:underline">
                  <FileSearch className="size-4" />{t('openInSource')}
                </Link>
              </li>
            ))}
          </ol>
        </DialogContent>
      )}
    </Dialog>
  );
}

function TopicDialog({open, onOpenChange, topic, topics, workspaceId}: {open: boolean; onOpenChange: (open: boolean) => void; topic?: Topic; topics: Topic[]; workspaceId: string}) {
  const t = useTranslations('Topics');
  const tc = useTranslations('Common');
  const errorText = useErrorText();
  const [title, setTitle] = useState(topic?.title ?? '');
  const [parent, setParent] = useState(topic?.parent_id ?? '');
  const [importance, setImportance] = useState<number | null>(null);
  const [resetImportance, setResetImportance] = useState(false);
  const [error, setError] = useState('');
  const save = useApiMutation((body: Record<string, unknown>) => (topic ? api(`topics/${topic.id}`, {method: 'PATCH', body}) : api('topics', {method: 'POST', body})), () => [keys.topics(workspaceId)]);
  const hasChildren = topic ? topics.some((item) => item.parent_id === topic.id) : false;
  const parents = topics.filter((item) => !item.parent_id && item.id !== topic?.id);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    const body: Record<string, unknown> = topic ? {} : {workspace_id: workspaceId, title: title.trim()};
    if (topic && title.trim() !== topic.title) body.title = title.trim();
    if ((topic?.parent_id ?? '') !== parent || (!topic && parent)) body.parent_id = parent || null;
    if (topic && importance !== null) body.importance = importance;
    if (topic && resetImportance) body.reset_importance = true;
    try {
      await save.mutateAsync(body);
      onOpenChange(false);
    } catch (e) {
      setError(errorText(e));
    }
  }
  const shownImportance = importance ?? topic?.importance ?? 3;
  return (
    <Dialog open={open} onOpenChange={(next) => { onOpenChange(next); if (next) { setTitle(topic?.title ?? ''); setParent(topic?.parent_id ?? ''); setImportance(null); setResetImportance(false); setError(''); } }}>
      <DialogContent title={topic ? t('editTitle') : t('addTitle')} closeLabel={tc('close')}>
        <form onSubmit={submit} className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="topic-title">{t('topicTitle')}</Label>
            <Input id="topic-title" autoFocus maxLength={160} value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="topic-parent">{t('parent')}</Label>
            <Select id="topic-parent" value={parent} disabled={hasChildren} onChange={(e) => setParent(e.target.value)}>
              <option value="">{t('noParent')}</option>
              {parents.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
            </Select>
          </div>
          {topic && (
            <fieldset className="grid gap-2">
              <legend className="text-sm font-semibold text-ink">{t('importance')}</legend>
              <div className="flex gap-2" role="radiogroup" aria-label={t('importance')}>
                {[1, 2, 3, 4, 5].map((value) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={shownImportance === value}
                    onClick={() => { setImportance(value); setResetImportance(false); }}
                    className={`grid size-10 place-items-center rounded-sm border text-sm font-bold transition-colors ${shownImportance === value ? 'border-brand bg-brand text-white' : 'border-line text-ink hover:border-brand'}`}
                  >
                    {value}
                  </button>
                ))}
              </div>
              {topic.importance_source === 'student' && (
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={resetImportance} onChange={(e) => { setResetImportance(e.target.checked); setImportance(null); }} className="size-4 accent-[#ec008c]" />
                  {t('importanceReset')}
                </label>
              )}
            </fieldset>
          )}
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <div className="flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>{tc('cancel')}</Button>
            <Button type="submit" disabled={save.isPending || !title.trim()}>{tc('save')}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function TopicActions({topic, topics, workspaceId}: {topic: Topic; topics: Topic[]; workspaceId: string}) {
  const t = useTranslations('Topics');
  const tc = useTranslations('Common');
  const tx = useTranslations('Explain');
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const status = useApiMutation((action: 'approve' | 'unapprove') => api(`topics/${topic.id}/${action}`, {method: 'POST'}), () => [keys.topics(workspaceId)]);
  const remove = useApiMutation(() => api(`topics/${topic.id}`, {method: 'DELETE'}), () => [keys.topics(workspaceId)]);
  return (
    <>
      {topic.status === 'draft' && (
        <Button size="sm" variant="soft" className="hidden md:inline-flex" disabled={status.isPending} onClick={() => status.mutate('approve')}>
          <CheckCircle2 />{t('approve')}
        </Button>
      )}
      <Menu>
        <MenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={`${tc('more')}: ${topic.title}`}><MoreHorizontal /></Button>
        </MenuTrigger>
        <MenuContent>
          {topic.status === 'draft'
            ? <MenuItem onSelect={() => status.mutate('approve')}><CheckCircle2 />{t('approve')}</MenuItem>
            : <MenuItem onSelect={() => status.mutate('unapprove')}><Undo2 />{t('unapprove')}</MenuItem>}
          {topic.status === 'approved' && (
            <MenuItem onSelect={() => router.push(explainHref(workspaceId, topic.title, topic.id, 'topic', tx('topicQuestion', {topic: topic.title})))}>
              <MessageCircleQuestion />{tx('explainTopic')}
            </MenuItem>
          )}
          <MenuItem onSelect={() => setEditing(true)}><Pencil />{t('edit')}</MenuItem>
          <MenuSeparator />
          <MenuItem danger onSelect={() => setDeleting(true)}><Trash2 />{tc('delete')}</MenuItem>
        </MenuContent>
      </Menu>
      <TopicDialog open={editing} onOpenChange={setEditing} topic={topic} topics={topics} workspaceId={workspaceId} />
      <ConfirmDialog open={deleting} onOpenChange={setDeleting} title={t('deleteTitle', {title: topic.title})} body={t('deleteBody')} confirmLabel={tc('delete')} onConfirm={() => remove.mutateAsync(undefined)} />
    </>
  );
}

function PastPaperQuestions({workspaceId, topics}: {workspaceId: string; topics: Topic[]}) {
  const t = useTranslations('Topics');
  const {data} = usePastPaperQuestions(workspaceId);
  if (!data) return null;
  return (
    <Card className="p-5 sm:p-6">
      <h2 className="text-lg">{t('questionsTitle')}</h2>
      {data.length === 0 ? <p className="mt-2 text-sm text-muted">{t('questionsEmpty')}</p> : (
        <ol className="mt-4 grid gap-3">
          {data.map((question) => (
            <li key={question.id} className="rounded-sm border border-line p-3">
              <p className="text-sm text-ink"><span className="font-bold text-plum">{question.label ? `${question.label} ` : ''}</span>{question.question_text}</p>
              <p className="mt-1 text-xs text-muted">{t('questionMeta', {marks: question.marks ?? 'none', year: question.year ?? 'none', file: question.document_name})}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {question.topic_ids.length === 0
                  ? <Badge tone="warning">{t('unmapped')}</Badge>
                  : question.topic_ids.map((id) => <Badge key={id} tone="brand">{topics.find((topic) => topic.id === id)?.title ?? '—'}</Badge>)}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

export function TopicsPanel({workspaceId}: {workspaceId: string}) {
  const t = useTranslations('Topics');
  const errorText = useErrorText();
  const {data: topics, isLoading} = useTopics(workspaceId);
  const {data: documents} = useDocuments(workspaceId);
  const proposeJob = useJob(workspaceId, 'propose');
  const mapJob = useJob(workspaceId, 'map_past_papers');
  const segmentJob = useJob(workspaceId, 'segment_past_paper');
  const [evidenceFor, setEvidenceFor] = useState<Topic | null>(null);
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<{tone: 'success' | 'danger'; text: string} | null>(null);
  const propose = useApiMutation(() => api<JobStatus>(`topics/workspace/${workspaceId}/propose`, {method: 'POST'}), () => [keys.job(workspaceId, 'propose')]);
  const mapPapers = useApiMutation(() => api<JobStatus>(`topics/workspace/${workspaceId}/map-past-papers`, {method: 'POST'}), () => [keys.job(workspaceId, 'map_past_papers')]);
  const approveAll = useApiMutation(() => api<{approved: number}>(`topics/workspace/${workspaceId}/approve-all`, {method: 'POST'}), () => [keys.topics(workspaceId)]);

  const syllabusReady = documents?.some((d) => d.material_role === 'syllabus' && d.state === 'ready');
  const pastPaperReady = documents?.some((d) => d.material_role === 'past_paper' && d.state === 'ready');
  const busy = ['queued', 'running'].includes(proposeJob.data?.state ?? '');
  const list = topics ?? [];
  const approved = list.filter((topic) => topic.status === 'approved').length;
  const run = (mutation: typeof propose) => mutation.mutate(undefined, {onError: (e) => setMessage({tone: 'danger', text: errorText(e)})});

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="grid gap-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-xl">{t('title')}</h2>
            <p className="mt-1 max-w-2xl text-sm text-muted">{t('subtitle')}</p>
          </div>
          {list.length > 0 && <Badge tone={approved === list.length ? 'success' : 'neutral'}>{t('summary', {approved, total: list.length})}</Badge>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="gradient" disabled={!syllabusReady || busy || propose.isPending} onClick={() => run(propose)}>
            {busy ? <Loader2 className="animate-spin" /> : list.length ? <RotateCcw /> : <Plus />}
            {list.length ? t('reproposing') : t('propose')}
          </Button>
          <Button variant="secondary" onClick={() => setAdding(true)}><Plus />{t('addTopic')}</Button>
          {list.some((topic) => topic.status === 'draft') && (
            <Button variant="secondary" disabled={approveAll.isPending} onClick={() => approveAll.mutate(undefined, {onSuccess: (r) => setMessage({tone: 'success', text: t('approvedAll', {count: r.approved})})})}>
              <CheckCheck />{t('approveAll')}
            </Button>
          )}
          {pastPaperReady && approved > 0 && (
            <Button variant="secondary" disabled={mapPapers.isPending || ['queued', 'running'].includes(mapJob.data?.state ?? '')} onClick={() => run(mapPapers)}>
              <FileSearch />{t('mapPapers')}
            </Button>
          )}
        </div>
        {!syllabusReady && <p className="text-sm text-muted">{t('needSyllabus')}</p>}
        {syllabusReady && list.length > 0 && <p className="text-xs text-muted">{t('proposeHint')}</p>}
        <div aria-live="polite" className="grid gap-2">
          <JobBanner job="propose" status={proposeJob.data} />
          <JobBanner job="segment_past_paper" status={segmentJob.data} />
          <JobBanner job="map_past_papers" status={mapJob.data} />
          {message && <Alert tone={message.tone}>{message.text}</Alert>}
        </div>
        {isLoading && <div className="grid gap-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16" />)}</div>}
        {topics && topics.length === 0 && (
          <Card className="grid place-items-center px-6 py-14 text-center">
            <FileSearch className="size-8 text-brand" />
            <h3 className="mt-4 text-lg">{t('empty')}</h3>
            <p className="mt-1 max-w-md text-sm text-muted">{t('emptyBody')}</p>
          </Card>
        )}
        {topics && topics.length > 0 && (
          <TopicTree topics={topics} onEvidence={setEvidenceFor} actions={(topic) => <TopicActions topic={topic} topics={topics} workspaceId={workspaceId} />} />
        )}
      </div>
      <aside className="grid h-fit gap-5">
        <PastPaperQuestions workspaceId={workspaceId} topics={list} />
      </aside>
      <EvidenceDrawer topic={evidenceFor} onClose={() => setEvidenceFor(null)} workspaceId={workspaceId} />
      <TopicDialog open={adding} onOpenChange={setAdding} topics={list} workspaceId={workspaceId} />
    </div>
  );
}
