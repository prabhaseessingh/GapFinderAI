'use client';

import {ArrowDownRight, ArrowUpRight, BookOpenCheck, ClipboardCheck, History, MessageCircleQuestion, Minus, RotateCcw, Target} from 'lucide-react';
import {useFormatter, useTranslations} from 'next-intl';
import {useState} from 'react';
import {Button} from '@/components/ui/button';
import {Accordion, AccordionItem, Alert, Badge, Card, Select, Skeleton} from '@/components/ui/primitives';
import {Link} from '@/i18n/navigation';
import {ApiError, type GapLabel, type GapReport, type UnitReport} from '@/lib/api';
import {useLatestReport, useReportById, useReportVersions} from '@/lib/queries';
import {cn} from '@/lib/utils';
import {CitationCard} from './citation-card';
import {explainHref} from './explain-link';
import {useErrorText} from './shared';

export const LABEL_TONE: Record<GapLabel, 'danger' | 'warning' | 'success' | 'neutral'> = {
  weak: 'danger',
  medium: 'warning',
  strong: 'success',
  limited_evidence: 'neutral'
};
const BAR: Record<GapLabel, string> = {weak: 'bg-danger', medium: 'bg-warning', strong: 'bg-success', limited_evidence: 'bg-line-strong'};

export function LabelBadge({label}: {label: GapLabel}) {
  const t = useTranslations('Report');
  return <Badge tone={LABEL_TONE[label]}>{t(`labels.${label}`)}</Badge>;
}

function Change({unit}: {unit: UnitReport}) {
  const t = useTranslations('Report');
  if (unit.previous_label === null) return null;
  if (unit.mastery === null || unit.previous_mastery === null) {
    return <p className="text-xs text-muted">{t('was', {label: t(`labels.${unit.previous_label}`)})}</p>;
  }
  const delta = Math.round((unit.mastery - unit.previous_mastery) * 10) / 10;
  const Icon = delta > 0 ? ArrowUpRight : delta < 0 ? ArrowDownRight : Minus;
  return (
    <p className={cn('inline-flex items-center gap-1 text-xs font-semibold', delta > 0 ? 'text-success' : delta < 0 ? 'text-danger' : 'text-muted')}>
      <Icon className="size-3.5" aria-hidden />
      {t('change', {delta: delta > 0 ? `+${delta}` : String(delta)})} · {t('was', {label: t(`labels.${unit.previous_label}`)})}
    </p>
  );
}

/** Mastery score bar coloured by label; Limited evidence shows no score. */
export function MasteryBar({label, mastery}: {label: GapLabel; mastery: number | null}) {
  const t = useTranslations('Report');
  if (mastery === null || label === 'limited_evidence') return <p className="text-sm font-semibold text-muted">{t('noMastery')}</p>;
  return (
    <>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-semibold text-muted">{t('mastery')}</span>
        <span className="font-bold text-ink">{t('masteryValue', {value: mastery})}</span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-soft" role="img" aria-label={t('masteryValue', {value: mastery})}>
        <div className={cn('h-full rounded-full', BAR[label])} style={{width: `${Math.max(2, mastery)}%`}} />
      </div>
    </>
  );
}

function UnitCard({unit, workspaceId, rank}: {unit: UnitReport; workspaceId: string; rank: number}) {
  const t = useTranslations('Report');
  const tq = useTranslations('Quiz');
  const tx = useTranslations('Explain');
  const f = unit.facts;
  const levels = (f.weak_levels ?? []).map((level) => t(`levels.${level}`)).join(', ');
  return (
    <Card className="p-5" data-testid="report-unit">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-muted">{t('priorityRank', {n: rank})}</p>
          <h3 className="mt-1 text-lg">{unit.title}</h3>
        </div>
        <LabelBadge label={unit.label} />
      </div>
      <div className="mt-4">
        <MasteryBar label={unit.label} mastery={unit.mastery} />
        <div className="mt-1.5"><Change unit={unit} /></div>
      </div>
      <dl className="mt-4 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-2">
        {f.latest_questions ? <div><dt className="sr-only">{t('latestScoreLabel')}</dt><dd>{t('latestScore', {correct: f.latest_correct ?? 0, max: f.latest_max ?? 0, count: f.latest_questions})}</dd></div> : null}
        <div><dt className="sr-only">{t('evaluatedLabel')}</dt><dd>{t('evaluated', {count: unit.evaluated_questions})}</dd></div>
        <div><dt className="sr-only">{t('importanceLabel')}</dt><dd>{t('importance', {value: unit.importance})} · {t(`importanceSource.${unit.importance_source ?? 'default'}`)}</dd></div>
        {unit.evaluated_questions > 0 && <div><dt className="sr-only">{t('confidenceLabel')}</dt><dd>{t('confidence', {value: Math.round(unit.confidence * 100)})}</dd></div>}
      </dl>
      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted">{t('reasonsTitle')}</p>
        <ul className="mt-1.5 grid gap-1 text-sm text-ink">
          {unit.reasons.map((code) => (
            <li key={code} className="flex gap-2"><span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-brand" />
              {t.has(`reasons.${code}`) ? t(`reasons.${code}` as 'reasons.score_weak', {levels, threshold: 2}) : code}
            </li>
          ))}
        </ul>
      </div>
      {f.subtopics && f.subtopics.length > 1 && (
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">{t('subtopics')}</p>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {f.subtopics.map((sub) => (
              <li key={sub.title}><Badge tone={sub.accuracy < 0.5 ? 'danger' : sub.accuracy < 0.75 ? 'warning' : 'success'}>{sub.title} · {Math.round(sub.accuracy * 100)}%</Badge></li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-sm bg-cyan-50 px-3 py-2">
        <p className="flex items-center gap-2 text-sm font-semibold text-ink"><Target className="size-4 shrink-0 text-[#0369a1]" />{t(`actions.${unit.action}`)}</p>
        {unit.topic_id && (
          <Button asChild size="sm" variant="secondary">
            <Link href={explainHref(workspaceId, unit.title, unit.topic_id, 'report', tx('topicQuestion', {topic: unit.title}))}><MessageCircleQuestion />{tx('explainTopic')}</Link>
          </Button>
        )}
      </div>
      {unit.missed.length > 0 && (
        <Accordion type="single" collapsible className="mt-3">
          <AccordionItem value="missed" question={t('missedTitle', {count: unit.missed.length})}>
            <ul className="grid gap-4">
              {unit.missed.map((m) => (
                <li key={`${m.attempt_id}-${m.question_id}`} className="grid gap-2">
                  <p className="flex flex-wrap items-center gap-2 text-xs font-semibold text-muted">
                    {tq(`types.${m.question_type}`)} · {t(`levels.${m.cognitive_level}`)}
                    {m.verdict && <Badge tone={m.verdict === 'partial' ? 'warning' : 'danger'}>{tq(`verdicts.${m.verdict}`)}</Badge>}
                    {m.score !== null && <span>{tq('scoreOf', {score: m.score, max: m.max_score})}</span>}
                  </p>
                  <p className="font-semibold text-ink">{m.prompt}</p>
                  {m.feedback && <p className="text-sm text-text">{m.feedback}</p>}
                  {unit.topic_id && (
                    <Link href={explainHref(workspaceId, unit.title, unit.topic_id, 'question', tx('questionQuestion', {question: m.prompt.slice(0, 600)}))}
                      className="inline-flex w-fit items-center gap-1 text-xs font-semibold text-brand hover:underline"><MessageCircleQuestion className="size-3.5" />{tx('explainQuestion')}</Link>
                  )}
                  {m.citations.length ? m.citations.map((c, i) => <CitationCard key={`${c.chunk_id}-${i}`} citation={c} workspaceId={workspaceId} />)
                    : <p className="text-xs text-muted">{tq('sourceUnavailable')}</p>}
                </li>
              ))}
            </ul>
          </AccordionItem>
        </Accordion>
      )}
    </Card>
  );
}

function ReportBody({report, workspaceId, isLatest}: {report: GapReport; workspaceId: string; isLatest: boolean}) {
  const t = useTranslations('Report');
  const format = useFormatter();
  const counts = report.summary.labels ?? {};
  const gaps = report.units.some((u) => u.label !== 'strong');
  return (
    <div className="grid gap-5">
      {!isLatest && <Alert tone="info" title={<span className="inline-flex items-center gap-2"><History className="size-4" />{t('historyTitle')}</span>}>{t('historyBody')}</Alert>}
      <Card className="grid gap-4 p-5 sm:grid-cols-[auto_1fr_auto] sm:items-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">{t('overall')}</p>
          <p className="mt-1 text-4xl font-bold text-ink" data-testid="overall-score">{report.summary.overall_score ?? '—'}<span className="text-lg text-muted">%</span></p>
        </div>
        <div className="grid gap-2">
          <p className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <Badge tone="brand">{report.quiz_kind === 'retest' ? <><RotateCcw className="size-3" />{t('kindRetest')}</> : <><ClipboardCheck className="size-3" />{t('kindDiagnostic')}</>}</Badge>
            {t('versionOn', {version: report.version, date: format.dateTime(new Date(report.created_at), {dateStyle: 'medium', timeStyle: 'short'})})}
          </p>
          <ul className="flex flex-wrap gap-2" aria-label={t('countsLabel')}>
            {(['weak', 'medium', 'strong', 'limited_evidence'] as const).map((label) => (
              <li key={label}><Badge tone={LABEL_TONE[label]}>{t(`labels.${label}`)}: {counts[label] ?? 0}</Badge></li>
            ))}
          </ul>
        </div>
        {isLatest && gaps && (
          <Button asChild variant="gradient"><Link href={`/app/w/${workspaceId}/quiz?retest=1`}><RotateCcw />{t('retestCta')}</Link></Button>
        )}
      </Card>
      <p className="text-sm text-muted">{t('policyNote')}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        {report.units.map((unit, i) => <UnitCard key={unit.topic_id ?? unit.title} unit={unit} workspaceId={workspaceId} rank={i + 1} />)}
      </div>
    </div>
  );
}

export function GapReportView({workspaceId}: {workspaceId: string}) {
  const t = useTranslations('Report');
  const errorText = useErrorText();
  const latest = useLatestReport(workspaceId);
  const versions = useReportVersions(workspaceId);
  const [selected, setSelected] = useState<string | null>(null);
  const older = useReportById(selected && selected !== latest.data?.id ? selected : null);
  if (latest.isLoading) return <Skeleton className="h-96" />;
  if (latest.error instanceof ApiError && latest.error.status === 404) {
    return (
      <Card className="grid justify-items-center gap-3 p-10 text-center">
        <BookOpenCheck className="size-10 text-brand" />
        <h2 className="text-xl">{t('emptyTitle')}</h2>
        <p className="max-w-lg text-sm text-muted">{t('emptyBody')}</p>
        <Button asChild variant="gradient"><Link href={`/app/w/${workspaceId}/quiz`}><ClipboardCheck />{t('emptyCta')}</Link></Button>
      </Card>
    );
  }
  if (latest.error || !latest.data) return <Alert tone="danger">{errorText(latest.error)}</Alert>;
  const report = older.data ?? latest.data;
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
            <Select className="h-9 w-auto py-0" value={report.id} onChange={(e) => setSelected(e.target.value)}>
              {versions.data?.map((v, i) => (
                <option key={v.id} value={v.id}>{t('versionOption', {version: v.version, latest: i === 0 ? 'yes' : 'no'})}</option>
              ))}
            </Select>
          </label>
        )}
      </div>
      {older.isLoading ? <Skeleton className="h-96" /> : <ReportBody report={report} workspaceId={workspaceId} isLatest={report.id === latest.data.id} />}
    </div>
  );
}
