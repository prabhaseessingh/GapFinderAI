'use client';

import {ClipboardCheck, Clock, Hourglass, Loader2, Play, Plus, RotateCcw, Target, Timer} from 'lucide-react';
import {useFormatter, useNow, useTranslations} from 'next-intl';
import {useState, type FormEvent} from 'react';
import {Button} from '@/components/ui/button';
import {Alert, Badge, Card, Dialog, DialogContent, Input, Label, Progress, Skeleton} from '@/components/ui/primitives';
import {useRouter} from '@/i18n/navigation';
import {api, type QuizAttempt, type QuizSummary} from '@/lib/api';
import {keys, useApiMutation, useDocuments, useLatestReport, useQuizzes, useTopics} from '@/lib/queries';
import {cn} from '@/lib/utils';
import {useErrorText} from './shared';

const COUNTS = [5, 10, 15] as const;

function NewQuizDialog({workspaceId, open, onOpenChange, kind}: {workspaceId: string; open: boolean; onOpenChange: (open: boolean) => void; kind: 'diagnostic' | 'retest'}) {
  const t = useTranslations('Quiz');
  const tc = useTranslations('Common');
  const errorText = useErrorText();
  const {data: topics = []} = useTopics(workspaceId);
  const approved = topics.filter((topic) => topic.status === 'approved');
  const units = approved.filter((topic) => !topic.parent_id || !approved.some((other) => other.id === topic.parent_id));
  const {data: report} = useLatestReport(workspaceId);
  // A re-test pre-selects units that are not Strong in the latest Gap Report (editable).
  const gapIds = (report?.units ?? []).filter((u) => u.label !== 'strong' && u.topic_id).map((u) => u.topic_id as string);
  const gapLabel = new Map((report?.units ?? []).map((u) => [u.topic_id, u.label]));
  const [count, setCount] = useState<(typeof COUNTS)[number]>(kind === 'retest' ? 5 : 10);
  const [scope, setScope] = useState<'all' | 'choose'>(kind === 'retest' ? 'choose' : 'all');
  const [chosen, setChosen] = useState<string[]>([]);
  const [timed, setTimed] = useState(false);
  const [minutes, setMinutes] = useState(15);
  const [error, setError] = useState('');
  const create = useApiMutation(
    (body: Record<string, unknown>) => api<QuizSummary>('quizzes', {method: 'POST', body}),
    () => [keys.quizzes(workspaceId)]
  );
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    try {
      await create.mutateAsync({
        workspace_id: workspaceId,
        kind,
        question_count: count,
        topic_ids: scope === 'choose' ? chosen : null,
        timer_mode: timed ? 'timed' : 'untimed',
        time_limit_minutes: timed ? minutes : null
      });
      onOpenChange(false);
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <Dialog open={open} onOpenChange={(next) => {
      onOpenChange(next);
      if (next) {
        setError('');
        setMinutes(Math.round(count * 1.5));
        if (kind === 'retest') { setScope('choose'); setChosen(gapIds.filter((id) => units.some((u) => u.id === id))); }
      }
    }}>
      <DialogContent title={kind === 'retest' ? t('retestTitle') : t('newTitle')} description={kind === 'retest' ? t('retestDescription') : t('newDescription')} closeLabel={tc('close')}>
        <form onSubmit={submit} className="grid gap-5">
          <fieldset>
            <legend className="text-sm font-semibold text-ink">{t('questionCount')}</legend>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {COUNTS.map((value) => (
                <label key={value} className={cn('cursor-pointer rounded-sm border px-3 py-2.5 text-center text-sm font-bold has-[:focus-visible]:ring-4 has-[:focus-visible]:ring-brand/20', count === value ? 'border-brand bg-pink-50 text-brand' : 'border-line text-ink')}>
                  <input type="radio" name="count" className="sr-only" checked={count === value} onChange={() => { setCount(value); setMinutes(Math.round(value * 1.5)); }} />
                  {t('questions', {count: value})}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend className="text-sm font-semibold text-ink">{t('scope')}</legend>
            <div className="mt-2 grid gap-2 text-sm">
              <label className="flex items-center gap-2"><input type="radio" name="scope" checked={scope === 'all'} onChange={() => setScope('all')} className="size-4 accent-[#ce007b]" />{t('scopeAll', {count: units.length})}</label>
              <label className="flex items-center gap-2"><input type="radio" name="scope" checked={scope === 'choose'} onChange={() => setScope('choose')} className="size-4 accent-[#ce007b]" />{t('scopeChoose')}</label>
            </div>
            {scope === 'choose' && (
              <ul className="mt-3 grid max-h-44 gap-1.5 overflow-y-auto rounded-sm border border-line p-3">
                {units.map((unit) => (
                  <li key={unit.id}>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" className="size-4 accent-[#ce007b]" checked={chosen.includes(unit.id)}
                        onChange={(e) => setChosen(e.target.checked ? [...chosen, unit.id] : chosen.filter((id) => id !== unit.id))} />
                      {unit.title}
                      {kind === 'retest' && gapLabel.get(unit.id) && <Badge tone={gapLabel.get(unit.id) === 'weak' ? 'danger' : gapLabel.get(unit.id) === 'medium' ? 'warning' : gapLabel.get(unit.id) === 'strong' ? 'success' : 'neutral'}>{t(`gapLabels.${gapLabel.get(unit.id)}`)}</Badge>}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </fieldset>
          <fieldset>
            <legend className="text-sm font-semibold text-ink">{t('timer')}</legend>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {[false, true].map((value) => (
                <label key={String(value)} className={cn('flex cursor-pointer items-center gap-2 rounded-sm border px-3 py-2.5 text-sm font-semibold has-[:focus-visible]:ring-4 has-[:focus-visible]:ring-brand/20', timed === value ? 'border-brand bg-pink-50 text-brand' : 'border-line text-ink')}>
                  <input type="radio" name="timer" className="sr-only" checked={timed === value} onChange={() => setTimed(value)} />
                  {value ? <Timer className="size-4" /> : <Clock className="size-4" />}
                  {value ? t('timed') : t('untimed')}
                </label>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">{timed ? t('timedHint') : t('untimedHint')}</p>
            {timed && (
              <div className="mt-3 flex items-center gap-3">
                <Label htmlFor="minutes">{t('minutes')}</Label>
                <Input id="minutes" type="number" min={1} max={240} value={minutes} onChange={(e) => setMinutes(Math.max(1, Math.min(240, Number(e.target.value) || 1)))} className="w-24" />
              </div>
            )}
          </fieldset>
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <div className="flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>{tc('cancel')}</Button>
            <Button type="submit" variant="gradient" disabled={create.isPending || (scope === 'choose' && chosen.length === 0)}>
              {create.isPending ? <Loader2 className="animate-spin" /> : kind === 'retest' ? <RotateCcw /> : <ClipboardCheck />}{kind === 'retest' ? t('createRetest') : t('create')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function QuizCard({quiz, workspaceId}: {quiz: QuizSummary; workspaceId: string}) {
  const t = useTranslations('Quiz');
  const format = useFormatter();
  const now = useNow({updateInterval: 60_000});
  const router = useRouter();
  const errorText = useErrorText();
  const [error, setError] = useState('');
  const start = useApiMutation(() => api<QuizAttempt>(`quizzes/${quiz.id}/attempts`, {method: 'POST'}), () => [keys.quizzes(workspaceId)]);
  const open = async () => {
    setError('');
    if (quiz.latest_attempt_id) return router.push(`/app/w/${workspaceId}/quiz/${quiz.latest_attempt_id}`);
    try {
      const attempt = await start.mutateAsync(undefined);
      router.push(`/app/w/${workspaceId}/quiz/${attempt.id}`);
    } catch (e) {
      setError(errorText(e));
    }
  };
  const generating = quiz.state === 'generating' || quiz.state === 'blueprint_draft';
  const failureKey = quiz.failure_code?.startsWith('QUESTION_REJECTED') ? 'QUESTION_REJECTED' : quiz.failure_code ?? 'fallback';
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-sm font-bold text-ink">
            {quiz.kind === 'retest' ? <RotateCcw className="size-4 text-brand" /> : <ClipboardCheck className="size-4 text-brand" />}{t('questions', {count: quiz.question_count})}
            {quiz.kind === 'retest' && <Badge tone="brand">{t('retestBadge')}</Badge>}
            <Badge tone={quiz.timer_mode === 'timed' ? 'warning' : 'neutral'}>
              {quiz.timer_mode === 'timed' ? <><Hourglass className="size-3" />{t('minutesShort', {count: Math.round((quiz.time_limit_seconds ?? 0) / 60)})}</> : t('untimed')}
            </Badge>
          </p>
          <p className="mt-1 text-xs text-muted">{format.relativeTime(new Date(quiz.created_at), now)}{quiz.unit_titles.length ? ` · ${quiz.unit_titles.join(' · ')}` : ''}</p>
        </div>
        {quiz.state === 'ready' && (
          <Button size="sm" variant={quiz.latest_attempt_state && quiz.latest_attempt_state !== 'in_progress' ? 'secondary' : 'primary'} disabled={start.isPending} onClick={() => void open()}>
            {quiz.latest_attempt_state === 'in_progress' ? <><RotateCcw />{t('resume')}</> : quiz.latest_attempt_id ? <><ClipboardCheck />{t('review')}</> : <><Play />{t('start')}</>}
          </Button>
        )}
      </div>
      {generating && (
        <div className="mt-4 grid gap-2" aria-live="polite">
          <p className="flex items-center gap-2 text-sm font-medium text-ink"><Loader2 className="size-4 animate-spin text-brand" />{t('generating', {done: quiz.progress_done, total: quiz.question_count})}</p>
          <Progress value={Math.max(4, (quiz.progress_done / quiz.question_count) * 100)} label={t('generating', {done: quiz.progress_done, total: quiz.question_count})} />
          <p className="text-xs text-muted">{t('generatingHint')}</p>
        </div>
      )}
      {quiz.latest_attempt_state && quiz.latest_attempt_state !== 'in_progress' && (
        <p className="mt-3 text-sm text-ink" data-testid="attempt-status">
          {quiz.latest_attempt_state === 'evaluated' ? t('scored', {score: quiz.latest_attempt_score ?? 0})
            : quiz.latest_attempt_state === 'evaluation_failed' ? <span className="text-danger">{t('evaluationFailedShort')}</span>
            : <span className="inline-flex items-center gap-1.5 text-muted"><Loader2 className="size-3.5 animate-spin" />{t('evaluating')}</span>}
        </p>
      )}
      {quiz.state === 'generation_failed' && (
        <Alert tone="danger" className="mt-3" title={t('failed')}>{t.has(`failures.${failureKey}`) ? t(`failures.${failureKey}` as 'failures.fallback') : t('failures.fallback')}</Alert>
      )}
      {quiz.not_tested.length > 0 && quiz.state !== 'generation_failed' && (
        <p className="mt-3 text-xs text-muted">{t('notTested', {units: quiz.not_tested.map((u) => u.title).join(', ')})}</p>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
    </Card>
  );
}

export function QuizList({workspaceId, openRetest = false}: {workspaceId: string; openRetest?: boolean}) {
  const t = useTranslations('Quiz');
  const {data: quizzes, isLoading} = useQuizzes(workspaceId);
  const {data: report} = useLatestReport(workspaceId);
  const [retesting, setRetesting] = useState(openRetest);
  const {data: topics = []} = useTopics(workspaceId);
  const {data: documents = []} = useDocuments(workspaceId);
  const [creating, setCreating] = useState(false);
  const hasApproved = topics.some((topic) => topic.status === 'approved');
  const hasAnswerMaterial = documents.some((d) => (d.material_role === 'textbook' || d.material_role === 'notes') && d.state === 'ready');
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl">{t('title')}</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">{t('subtitle')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {report && <Button variant="secondary" disabled={!hasAnswerMaterial} onClick={() => setRetesting(true)}><Target />{t('newRetest')}</Button>}
          <Button variant="gradient" disabled={!hasApproved || !hasAnswerMaterial} onClick={() => setCreating(true)}><Plus />{t('new')}</Button>
        </div>
      </div>
      {!hasApproved && <Alert tone="info">{t('needApproved')}</Alert>}
      {hasApproved && !hasAnswerMaterial && <Alert tone="info">{t('needMaterial')}</Alert>}
      {isLoading && <div className="grid gap-3">{[0, 1].map((i) => <Skeleton key={i} className="h-24" />)}</div>}
      {quizzes?.length === 0 && hasApproved && hasAnswerMaterial && <Card className="p-8 text-center text-muted">{t('empty')}</Card>}
      <div className="grid gap-3 lg:grid-cols-2">{quizzes?.map((quiz) => <QuizCard key={quiz.id} quiz={quiz} workspaceId={workspaceId} />)}</div>
      <NewQuizDialog workspaceId={workspaceId} kind="diagnostic" open={creating} onOpenChange={setCreating} />
      {report && <NewQuizDialog workspaceId={workspaceId} kind="retest" open={retesting} onOpenChange={setRetesting} />}
    </div>
  );
}
