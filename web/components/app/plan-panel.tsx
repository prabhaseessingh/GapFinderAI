'use client';

import {AlertTriangle, CalendarCheck, CalendarDays, CheckCircle2, ClipboardCheck, History, Loader2, RotateCcw, Save} from 'lucide-react';
import {useFormatter, useTranslations} from 'next-intl';
import {useState, type FormEvent, type ReactNode} from 'react';
import {Button} from '@/components/ui/button';
import {Alert, Badge, Card, Input, Label, Select, Skeleton} from '@/components/ui/primitives';
import {Link} from '@/i18n/navigation';
import {api, type PlanSession, type PlanState, type RevisionPlan, type StudyPreferences, type Weekday} from '@/lib/api';
import {diagnosisKeys, keys, useApiMutation, usePlanById, usePlanState, usePlanVersions} from '@/lib/queries';
import {cn} from '@/lib/utils';
import {LabelBadge} from './gap-report';
import {useErrorText} from './shared';

const WEEKDAYS: Weekday[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

function localTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function isoDate(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function AvailabilityForm({workspaceId, current, onSaved}: {workspaceId: string; current: StudyPreferences | null; onSaved?: () => void}) {
  const t = useTranslations('Plan');
  const errorText = useErrorText();
  const [examDate, setExamDate] = useState(() => current?.exam_date ?? isoDate(new Date(Date.now() + 21 * 86_400_000)));
  const [minutes, setMinutes] = useState(current?.minutes_per_day ?? 60);
  const [days, setDays] = useState<Weekday[]>(current?.available_weekdays ?? ['mon', 'tue', 'wed', 'thu', 'fri']);
  const [error, setError] = useState('');
  const save = useApiMutation(
    (body: Record<string, unknown>) => api<PlanState>(`workspaces/${workspaceId}/study-preferences`, {method: 'PUT', body}),
    () => diagnosisKeys(workspaceId)
  );
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    try {
      await save.mutateAsync({exam_date: examDate, minutes_per_day: minutes, available_weekdays: WEEKDAYS.filter((d) => days.includes(d)), timezone: current?.timezone ?? localTimezone()});
      onSaved?.();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <form onSubmit={submit} className="grid gap-5" aria-label={t('availabilityTitle')}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor="exam-date">{t('examDate')}</Label>
          <Input id="exam-date" type="date" required min={isoDate(new Date())} value={examDate} onChange={(e) => setExamDate(e.target.value)} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="minutes-per-day">{t('minutesPerDay')}</Label>
          <Input id="minutes-per-day" type="number" required min={10} max={720} step={5} value={minutes} onChange={(e) => setMinutes(Number(e.target.value) || 10)} />
        </div>
      </div>
      <fieldset>
        <legend className="text-sm font-semibold text-ink">{t('weekdays')}</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {WEEKDAYS.map((day) => {
            const on = days.includes(day);
            return (
              <label key={day} className={cn('cursor-pointer rounded-sm border px-3 py-2 text-sm font-semibold has-[:focus-visible]:ring-4 has-[:focus-visible]:ring-brand/20', on ? 'border-brand bg-pink-50 text-brand' : 'border-line text-ink')}>
                <input type="checkbox" className="sr-only" checked={on} onChange={(e) => setDays(e.target.checked ? [...days, day] : days.filter((d) => d !== day))} />
                {t(`days.${day}`)}
              </label>
            );
          })}
        </div>
      </fieldset>
      <p className="text-xs text-muted">{t('timezone', {zone: current?.timezone ?? localTimezone()})}</p>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <div>
        <Button type="submit" variant="gradient" disabled={save.isPending || days.length === 0}>
          {save.isPending ? <Loader2 className="animate-spin" /> : <Save />}{current ? t('updatePlan') : t('buildPlan')}
        </Button>
      </div>
    </form>
  );
}

function SessionRow({session, plan, workspaceId}: {session: PlanSession; plan: RevisionPlan; workspaceId: string}) {
  const t = useTranslations('Plan');
  const errorText = useErrorText();
  const [error, setError] = useState('');
  const toggle = useApiMutation(
    (done: boolean) => api<PlanSession>(`plan-sessions/${session.id}/completion`, {method: 'PUT', body: {done}}),
    () => [keys.plan(workspaceId), keys.planById(plan.id), keys.progress(workspaceId)]
  );
  // Optimistic tick: shown immediately, cleared once the refreshed plan arrives (or on error).
  const [optimistic, setOptimistic] = useState<boolean | null>(null);
  const done = optimistic ?? Boolean(session.completed_at);
  const label = session.activity === 'retest' ? t('retestSession') : session.topic_title ?? '';
  const change = async (next: boolean) => {
    setError('');
    setOptimistic(next);
    try {
      await toggle.mutateAsync(next);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setOptimistic(null);
    }
  };
  return (
    <SessionLine session={session} done={done} error={error}
      control={plan.is_latest ? (
        <input type="checkbox" className="size-5 accent-[#ce007b]" checked={done} aria-busy={toggle.isPending}
          aria-label={t('markDone', {session: label})}
          onChange={(e) => { if (!toggle.isPending) void change(e.target.checked); }} />
      ) : done ? <CheckCircle2 className="size-5 text-success" aria-label={t('done')} /> : <span className="size-5" />}>
      {session.activity === 'retest' && plan.is_latest && (
        <Button asChild size="sm" variant="secondary"><Link href={`/app/w/${workspaceId}/quiz?retest=1`}><RotateCcw />{t('startRetest')}</Link></Button>
      )}
    </SessionLine>
  );
}

/** One scheduled session row (presentational; shared with the landing showcase). */
export function SessionLine({session, done, control, error, children}: {
  session: PlanSession; done: boolean; control: ReactNode; error?: string; children?: ReactNode;
}) {
  const t = useTranslations('Plan');
  const label = session.activity === 'retest' ? t('retestSession') : session.topic_title ?? '';
  return (
    <li className={cn('flex flex-wrap items-center gap-3 rounded-sm border px-3 py-2.5', done ? 'border-success/30 bg-success-50' : 'border-line bg-surface')}>
      {control}
      <div className="min-w-0 flex-1">
        <p className={cn('text-sm font-semibold text-ink', done && 'line-through decoration-success/60')}>{label}</p>
        {session.focus.length > 0 && <p className="text-xs text-muted">{t('focus', {topics: session.focus.join(', ')})}</p>}
        {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      </div>
      <Badge tone={session.activity === 'retest' ? 'brand' : session.activity === 'review' ? 'success' : 'info'}>{t(`activities.${session.activity}`)}</Badge>
      <span className="text-sm font-semibold text-muted">{t('minutes', {count: session.minutes})}</span>
      {children}
    </li>
  );
}

function PlanView({plan, workspaceId}: {plan: RevisionPlan; workspaceId: string}) {
  const t = useTranslations('Plan');
  const format = useFormatter();
  const byDay = new Map<string, PlanSession[]>();
  plan.sessions.forEach((s) => byDay.set(s.day, [...(byDay.get(s.day) ?? []), s]));
  const hours = (m: number) => t('duration', {hours: Math.floor(m / 60), minutes: m % 60});
  return (
    <div className="grid gap-5">
      {!plan.is_latest && <Alert tone="info" title={<span className="inline-flex items-center gap-2"><History className="size-4" />{t('historyTitle')}</span>}>{t('historyBody')}</Alert>}
      {plan.status === 'shortfall' ? (
        <Alert tone="warning" title={<span className="inline-flex items-center gap-2"><AlertTriangle className="size-4" />{t('shortfallTitle')}</span>}>
          <p>{t('shortfallBody', {need: hours(plan.demand_minutes), have: hours(plan.available_minutes), missing: hours(plan.demand_minutes - plan.scheduled_minutes)})}</p>
          <ul className="mt-2 grid gap-1" data-testid="shortfall-list">
            {plan.shortfall.map((s) => <li key={s.topic_id} className="flex flex-wrap items-center gap-2"><LabelBadge label={s.label} /><span className="font-semibold text-ink">{s.title}</span><span>— {t('uncovered', {time: hours(s.minutes)})}</span></li>)}
          </ul>
          <p className="mt-2 text-xs">{t('shortfallHint')}</p>
        </Alert>
      ) : (
        <Alert tone="success" title={<span className="inline-flex items-center gap-2"><CalendarCheck className="size-4" />{t('feasibleTitle')}</span>}>
          {t('feasibleBody', {need: hours(plan.demand_minutes), have: hours(plan.available_minutes)})}
        </Alert>
      )}
      <p className="text-sm text-muted">{t('planMeta', {version: plan.version, report: plan.report_version, date: format.dateTime(new Date(`${plan.preferences.exam_date}T00:00:00`), {dateStyle: 'long'})})}</p>
      <p className="text-xs text-muted">{t('completionNote')}</p>
      {plan.sessions.length === 0 ? <Card className="p-6 text-center text-muted">{t('noSessions')}</Card> : (
        <ol className="grid gap-4">
          {[...byDay.entries()].map(([day, sessions]) => (
            <li key={day}>
              <Card className="p-4">
                <h3 className="flex items-center justify-between gap-2 text-base">
                  <span className="inline-flex items-center gap-2"><CalendarDays className="size-4 text-brand" />{format.dateTime(new Date(`${day}T00:00:00`), {weekday: 'long', day: 'numeric', month: 'short'})}</span>
                  <span className="text-sm font-semibold text-muted">{t('minutes', {count: sessions.reduce((sum, s) => sum + s.minutes, 0)})}</span>
                </h3>
                <ul className="mt-3 grid gap-2">{sessions.map((s) => <SessionRow key={s.id} session={s} plan={plan} workspaceId={workspaceId} />)}</ul>
              </Card>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function PlanPanel({workspaceId}: {workspaceId: string}) {
  const t = useTranslations('Plan');
  const errorText = useErrorText();
  const {data, isLoading, error} = usePlanState(workspaceId);
  const versions = usePlanVersions(workspaceId);
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const older = usePlanById(selected && selected !== data?.plan?.id ? selected : null);
  if (isLoading) return <Skeleton className="h-96" />;
  if (error || !data) return <Alert tone="danger">{errorText(error)}</Alert>;
  const plan = older.data ?? data.plan;
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl">{t('title')}</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">{t('subtitle')}</p>
        </div>
        {(versions.data?.length ?? 0) > 1 && (
          <label className="flex items-center gap-2 text-sm font-semibold text-muted">
            {t('versionLabel')}
            <Select className="h-9 w-auto py-0" value={plan?.id ?? ''} onChange={(e) => setSelected(e.target.value)}>
              {versions.data?.map((v, i) => <option key={v.id} value={v.id}>{t('versionOption', {version: v.version, latest: i === 0 ? 'yes' : 'no'})}</option>)}
            </Select>
          </label>
        )}
      </div>
      {data.next_action === 'take_diagnostic' && (
        <Alert tone="info" title={t('needReportTitle')} action={<Button asChild size="sm"><Link href={`/app/w/${workspaceId}/quiz`}><ClipboardCheck />{t('needReportCta')}</Link></Button>}>
          {t('needReportBody')}
        </Alert>
      )}
      {(data.next_action === 'set_availability' || editing || (data.preferences && !data.plan && data.next_action === 'none')) ? (
        <Card className="p-5">
          <h3 className="text-lg">{t('availabilityTitle')}</h3>
          <p className="mt-1 text-sm text-muted">{t('availabilityHint')}</p>
          {data.preferences && !data.plan && !editing && <Alert tone="warning" className="mt-3">{t('examPassed')}</Alert>}
          <div className="mt-4"><AvailabilityForm workspaceId={workspaceId} current={data.preferences} onSaved={() => { setEditing(false); setSelected(null); }} /></div>
        </Card>
      ) : data.preferences && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <p className="text-sm text-ink">{t('availabilitySummary', {minutes: data.preferences.minutes_per_day, days: data.preferences.available_weekdays.map((d) => t(`days.${d}`)).join(', ')})}</p>
          <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>{t('editAvailability')}</Button>
        </Card>
      )}
      {older.isLoading ? <Skeleton className="h-64" /> : plan && <PlanView plan={plan} workspaceId={workspaceId} />}
    </div>
  );
}
