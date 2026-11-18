'use client';

import {CalendarCheck, LineChart as LineIcon, Table2} from 'lucide-react';
import {useFormatter, useTranslations} from 'next-intl';
import {useState} from 'react';
import {CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {Button} from '@/components/ui/button';
import {Alert, Card, Progress, Skeleton} from '@/components/ui/primitives';
import {Link} from '@/i18n/navigation';
import type {ProgressData} from '@/lib/api';
import {useProgress} from '@/lib/queries';
import {useErrorText} from './shared';
import {LabelBadge} from './gap-report';

/** Validated categorical order (dataviz reference palette, light surface): fixed by unit, never cycled. */
const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
const MAX_SERIES = SERIES.length;
const AXIS = {stroke: '#d3d8e2', tick: {fill: '#5f6876', fontSize: 12}};

function TableView({data}: {data: ProgressData}) {
  const t = useTranslations('Progress');
  const tr = useTranslations('Report');
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] border-collapse text-sm">
        <caption className="sr-only">{t('tableCaption')}</caption>
        <thead>
          <tr className="border-b border-line text-left text-xs uppercase tracking-wider text-muted">
            <th scope="col" className="py-2 pr-3">{t('unit')}</th>
            {data.reports.map((r) => <th key={r.report_id} scope="col" className="py-2 pr-3">{t('reportShort', {version: r.version})}</th>)}
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-line font-semibold text-ink">
            <th scope="row" className="py-2 pr-3 text-left">{t('overall')}</th>
            {data.reports.map((r) => <td key={r.report_id} className="py-2 pr-3">{r.overall_score ?? '—'}%</td>)}
          </tr>
          {data.unit_titles.map((title) => (
            <tr key={title} className="border-b border-line">
              <th scope="row" className="py-2 pr-3 text-left font-semibold text-ink">{title}</th>
              {data.reports.map((r) => (
                <td key={r.report_id} className="py-2 pr-3">
                  {r.labels[title] ? <span className="inline-flex flex-wrap items-center gap-1.5">{r.units[title] ?? '—'}<LabelBadge label={r.labels[title]} /></span> : <span className="text-muted">{tr('notInReport')}</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ProgressPanel({workspaceId}: {workspaceId: string}) {
  const t = useTranslations('Progress');
  const format = useFormatter();
  const errorText = useErrorText();
  const {data, isLoading, error} = useProgress(workspaceId);
  const [view, setView] = useState<'chart' | 'table'>('chart');
  if (isLoading) return <Skeleton className="h-96" />;
  if (error || !data) return <Alert tone="danger">{errorText(error)}</Alert>;
  const c = data.completion;
  const header = (
    <div>
      <h2 className="text-xl">{t('title')}</h2>
      <p className="mt-1 max-w-2xl text-sm text-muted">{t('subtitle')}</p>
    </div>
  );
  if (data.reports.length === 0) {
    return (
      <div className="grid gap-6">{header}
        <Alert tone="info" action={<Button asChild size="sm"><Link href={`/app/w/${workspaceId}/quiz`}>{t('emptyCta')}</Link></Button>}>{t('empty')}</Alert>
      </div>
    );
  }
  const label = (version: number, kind: string | null) => `${t('reportShort', {version})}${kind === 'retest' ? ` · ${t('retest')}` : ''}`;
  const charted = data.unit_titles.slice(0, MAX_SERIES);
  // Index keys: unit titles may contain dots, which Recharts would read as nested paths.
  const rows = data.reports.map((r) => ({
    name: label(r.version, r.quiz_kind),
    date: format.dateTime(new Date(r.created_at), {dateStyle: 'medium'}),
    overall: r.overall_score,
    ...Object.fromEntries(charted.map((title, i) => [`u${i}`, r.units[title] ?? null]))
  }));
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        {header}
        <div className="flex gap-2" role="group" aria-label={t('viewLabel')}>
          <Button size="sm" variant={view === 'chart' ? 'primary' : 'secondary'} aria-pressed={view === 'chart'} onClick={() => setView('chart')}><LineIcon />{t('chart')}</Button>
          <Button size="sm" variant={view === 'table' ? 'primary' : 'secondary'} aria-pressed={view === 'table'} onClick={() => setView('table')}><Table2 />{t('table')}</Button>
        </div>
      </div>

      {view === 'table' ? <Card className="p-5"><TableView data={data} /></Card> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-5">
            <h3 className="text-base">{t('overallTitle')}</h3>
            <p className="text-xs text-muted">{t('overallHint')}</p>
            <div className="mt-3 h-64" role="img" aria-label={t('overallAria', {values: data.reports.map((r) => `${label(r.version, r.quiz_kind)}: ${r.overall_score ?? '—'}%`).join('; ')})}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} margin={{top: 12, right: 16, bottom: 4, left: -16}}>
                  <CartesianGrid stroke="#edf0f4" vertical={false} />
                  <XAxis dataKey="name" {...AXIS} tickLine={false} />
                  <YAxis domain={[0, 100]} {...AXIS} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v) => [`${v}%`, t('overall')]} labelFormatter={(l, p) => `${l} · ${p?.[0]?.payload?.date ?? ''}`} />
                  <Line type="monotone" dataKey="overall" stroke="#ce007b" strokeWidth={2} dot={{r: 4, strokeWidth: 2, fill: '#fff'}} activeDot={{r: 6}} isAnimationActive={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card className="p-5">
            <h3 className="text-base">{t('unitsTitle')}</h3>
            <p className="text-xs text-muted">{t('unitsHint')}</p>
            <div className="mt-3 h-64" role="img" aria-label={t('unitsAria')}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} margin={{top: 12, right: 16, bottom: 4, left: -16}}>
                  <CartesianGrid stroke="#edf0f4" vertical={false} />
                  <XAxis dataKey="name" {...AXIS} tickLine={false} />
                  <YAxis domain={[0, 100]} {...AXIS} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v, name) => [v === null || v === undefined ? t('limited') : String(v), String(name)]} />
                  {charted.length > 1 && <Legend iconType="plainline" wrapperStyle={{fontSize: 12, color: '#424c58'}} />}
                  {charted.map((title, i) => (
                    <Line key={title} type="monotone" dataKey={`u${i}`} name={title} stroke={SERIES[i]} strokeWidth={2} dot={{r: 4, strokeWidth: 2, fill: '#fff'}} activeDot={{r: 6}} isAnimationActive={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
            {data.unit_titles.length > MAX_SERIES && <p className="mt-2 text-xs text-muted">{t('moreUnits', {count: data.unit_titles.length - MAX_SERIES})}</p>}
          </Card>
        </div>
      )}

      <Card className="p-5">
        <h3 className="flex items-center gap-2 text-base"><CalendarCheck className="size-4 text-brand" />{t('completionTitle')}</h3>
        <p className="text-xs text-muted">{t('completionHint')}</p>
        {c.sessions_planned === 0 ? <p className="mt-3 text-sm text-muted">{t('noPlan')}</p> : (
          <div className="mt-3 grid gap-2">
            <p className="text-sm text-ink" data-testid="completion-summary">{t('completion', {done: c.sessions_completed, total: c.sessions_planned, minutesDone: c.minutes_completed, minutesTotal: c.minutes_planned})}</p>
            <Progress value={(c.minutes_completed / Math.max(1, c.minutes_planned)) * 100} label={t('completion', {done: c.sessions_completed, total: c.sessions_planned, minutesDone: c.minutes_completed, minutesTotal: c.minutes_planned})} />
          </div>
        )}
      </Card>
    </div>
  );
}
