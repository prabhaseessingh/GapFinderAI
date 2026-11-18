'use client';

import {CheckCircle2, ChevronRight, CircleDashed, FileText, MoreHorizontal, Pencil, Quote} from 'lucide-react';
import {useTranslations} from 'next-intl';
import type {ReactNode} from 'react';
import type {Topic} from '@/lib/api';
import {Badge, Tooltip} from '@/components/ui/primitives';
import {cn} from '@/lib/utils';

export function ImportanceMeter({topic, compact}: {topic: Topic; compact?: boolean}) {
  const t = useTranslations('Topics');
  const basis = topic.importance_basis;
  const reason =
    topic.importance_source === 'student'
      ? t('importanceStudent')
      : topic.importance_source === 'past_papers'
        ? t('importancePastPapers', {
            questions: basis.past_paper_questions ?? 0,
            marks: basis.weighted_marks ?? 0,
            years: basis.years?.length ? t('importanceYears', {years: basis.years.join(', ')}) : ''
          })
        : (basis.workspace_past_paper_questions ?? 0) > 0
          ? t('importanceUnmatched')
          : t('importanceDefault');
  return (
    <Tooltip content={reason}>
      <button type="button" className="inline-flex shrink-0 cursor-help items-center gap-1.5 rounded-full" aria-label={`${t('importanceValue', {value: topic.importance})}. ${reason}`}>
        <span className="flex gap-0.5" aria-hidden>
          {[1, 2, 3, 4, 5].map((level) => (
            <span key={level} className={cn('rounded-full', compact ? 'h-2.5 w-1' : 'h-3.5 w-1.5', level <= topic.importance ? 'bg-brand-gradient-vivid' : 'bg-soft')} />
          ))}
        </span>
        {!compact && topic.importance_source === 'student' && <Pencil aria-hidden className="size-3 text-plum" />}
      </button>
    </Tooltip>
  );
}

type RowSlots = {actions?: (topic: Topic) => ReactNode; onEvidence?: (topic: Topic) => void};

function TopicRow({topic, nested, slots, compact}: {topic: Topic; nested?: boolean; slots: RowSlots; compact?: boolean}) {
  const t = useTranslations('Topics');
  return (
    <li
      className={cn(
        'group flex items-center gap-3 rounded-md border bg-surface transition-[border-color,box-shadow] duration-200',
        compact ? 'px-2.5 py-2' : 'px-4 py-3 hover:border-line-strong hover:shadow-card',
        topic.status === 'approved' ? 'border-success/25' : 'border-line',
        nested && (compact ? 'ml-4' : 'ml-6 sm:ml-10')
      )}
    >
      {topic.status === 'approved' ? (
        <CheckCircle2 className={cn('shrink-0 text-success', compact ? 'size-3.5' : 'size-5')} aria-label={t('approved')} />
      ) : (
        <CircleDashed className={cn('shrink-0 text-muted', compact ? 'size-3.5' : 'size-5')} aria-label={t('draft')} />
      )}
      <div className="min-w-0 flex-1">
        <p className={cn('truncate font-semibold text-ink', compact ? 'text-[11px] leading-4' : 'text-[15px]')}>
          {nested && <ChevronRight className="mr-0.5 inline size-3.5 text-muted" aria-hidden />}
          {topic.title}
        </p>
        {!compact && (
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <button
              type="button"
              disabled={!slots.onEvidence || topic.citation_count === 0}
              onClick={() => slots.onEvidence?.(topic)}
              className="inline-flex items-center gap-1 rounded-sm font-medium enabled:text-plum enabled:hover:text-brand disabled:cursor-default"
            >
              <Quote className="size-3.5" />
              {t('citations', {count: topic.citation_count})}
            </button>
            <span className="inline-flex items-center gap-1"><FileText className="size-3.5" />{t('pastPaperCount', {count: topic.importance_basis.past_paper_questions ?? topic.past_paper_question_count})}</span>
          </div>
        )}
      </div>
      <ImportanceMeter topic={topic} compact={compact} />
      {!compact && <Badge tone={topic.status === 'approved' ? 'success' : 'neutral'} className="hidden sm:inline-flex">{t(topic.status)}</Badge>}
      {slots.actions?.(topic) ?? (compact ? null : <MoreHorizontal className="size-4 text-transparent" aria-hidden />)}
    </li>
  );
}

/** Two-level topic tree. Used by the app and (compact, read-only) inside the landing phone mockup. */
export function TopicTree({topics, compact, ...slots}: {topics: Topic[]; compact?: boolean} & RowSlots) {
  const roots = topics.filter((topic) => !topic.parent_id || !topics.some((other) => other.id === topic.parent_id));
  return (
    <ul className={cn('flex flex-col', compact ? 'gap-1.5' : 'gap-2')}>
      {roots.map((root) => (
        <li key={root.id} className="contents">
          <ul className={cn('flex flex-col', compact ? 'gap-1.5' : 'gap-2')}>
            <TopicRow topic={root} slots={slots} compact={compact} />
            {topics.filter((child) => child.parent_id === root.id).map((child) => (
              <TopicRow key={child.id} topic={child} nested slots={slots} compact={compact} />
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
