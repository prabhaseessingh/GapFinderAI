'use client';

import {ArrowLeft, ArrowRight, CheckCircle2, CircleDashed, Clock, Hourglass, Loader2, Lock, RotateCcw, Send, Target, XCircle} from 'lucide-react';
import {useQueryClient} from '@tanstack/react-query';
import {useLocale, useTranslations} from 'next-intl';
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Button} from '@/components/ui/button';
import {Alert, Badge, Card, Dialog, DialogContent, Skeleton} from '@/components/ui/primitives';
import {Link} from '@/i18n/navigation';
import {api, type AttemptAnswer, type QuizAttempt, type QuizQuestion} from '@/lib/api';
import {diagnosisKeys, keys, useAttempt} from '@/lib/queries';
import {cn} from '@/lib/utils';
import {CitationCard} from './citation-card';
import {useErrorText} from './shared';

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

function clock(totalSeconds: number) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

/** Server-anchored timer: elapsed for untimed attempts, remaining for timed ones. */
function useAttemptClock(attempt: QuizAttempt | undefined, receivedAt: number) {
  const [now, setNow] = useState(() => Date.now());
  // server_now was true at receivedAt (client clock): that difference corrects client clock skew.
  const offset = useMemo(() => (attempt ? Date.parse(attempt.server_now) - receivedAt : 0), [attempt, receivedAt]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  if (!attempt) return {elapsed: 0, remaining: null as number | null};
  const serverNow = now + offset;
  return {
    elapsed: (serverNow - Date.parse(attempt.started_at)) / 1000,
    remaining: attempt.deadline_at ? (Date.parse(attempt.deadline_at) - serverNow) / 1000 : null
  };
}

export function AnswerInput({question, value, onChange, disabled}: {question: QuizQuestion; value: AttemptAnswer; onChange: (v: AttemptAnswer) => void; disabled?: boolean}) {
  const t = useTranslations('Quiz');
  if (question.question_type === 'short_answer') {
    return (
      <div>
        <label htmlFor={`answer-${question.id}`} className="text-sm font-semibold text-ink">{t('yourAnswer')}</label>
        <textarea
          id={`answer-${question.id}`}
          disabled={disabled}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
          maxLength={5000}
          rows={7}
          className="mt-2 w-full rounded-sm border border-line-strong bg-surface p-3.5 text-[15px] text-ink focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15"
        />
      </div>
    );
  }
  const choices = question.question_type === 'mcq'
    ? (question.options ?? []).map((o) => ({key: o.id, value: o.id as AttemptAnswer, label: o.text}))
    : [{key: 'T', value: true as AttemptAnswer, label: t('true')}, {key: 'F', value: false as AttemptAnswer, label: t('false')}];
  return (
    <div role="radiogroup" aria-label={t('yourAnswer')} className="grid gap-2.5">
      {choices.map((choice) => {
        const selected = value === choice.value;
        return (
          <button
            key={choice.key}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(choice.value)}
            className={cn('flex items-start gap-3 rounded-md border px-4 py-3 text-left text-[15px] transition-colors', selected ? 'border-brand bg-pink-50 text-ink shadow-glow-sm' : 'border-line bg-surface text-ink hover:border-line-strong')}
          >
            <span className={cn('grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold', selected ? 'bg-brand text-white' : 'bg-soft text-muted')}>{choice.key}</span>
            <span className="pt-0.5">{choice.label}</span>
          </button>
        );
      })}
    </div>
  );
}

const VERDICT_TONE = {correct: 'success', partial: 'warning', incorrect: 'danger', unanswered: 'neutral', insufficient_evidence: 'neutral'} as const;

function ReviewItem({question, answer, workspaceId}: {question: QuizQuestion; answer: AttemptAnswer; workspaceId: string}) {
  const t = useTranslations('Quiz');
  const objective = question.question_type !== 'short_answer';
  const localCorrect = question.question_type === 'mcq' ? answer === question.correct_option_id : question.question_type === 'true_false' ? answer === question.correct_boolean : null;
  const verdict = question.verdict ?? (objective ? (answer === null || answer === undefined ? 'unanswered' : localCorrect ? 'correct' : 'incorrect') : null);
  const show = (value: AttemptAnswer) =>
    value === null || value === undefined || value === '' ? t('noAnswer')
      : typeof value === 'boolean' ? (value ? t('true') : t('false'))
      : question.question_type === 'mcq' ? `${value}. ${question.options?.find((o) => o.id === value)?.text ?? ''}` : value;
  return (
    <Card className="p-5" data-testid="review-item">
      <p className="flex flex-wrap items-center gap-2 text-xs font-semibold text-muted">
        <span>{t('questionN', {n: question.position + 1})}</span><span>· {question.topic_title}</span>
        {verdict && (
          <Badge tone={VERDICT_TONE[verdict]}>
            {verdict === 'correct' ? <CheckCircle2 className="size-3.5" /> : verdict === 'partial' ? <CircleDashed className="size-3.5" /> : <XCircle className="size-3.5" />}
            {t(`verdicts.${verdict}`)}
          </Badge>
        )}
        {question.score !== undefined && question.score !== null && <span>{t('scoreOf', {score: question.score, max: question.max_score})}</span>}
      </p>
      <p className="mt-2 font-semibold text-ink">{question.prompt}</p>
      <dl className="mt-3 grid gap-2 text-sm">
        <div><dt className="font-semibold text-muted">{t('yourAnswer')}</dt><dd className="whitespace-pre-wrap text-ink">{show(answer)}</dd></div>
        {question.feedback && <div><dt className="font-semibold text-muted">{t('feedback')}</dt><dd className="text-ink">{question.feedback}</dd></div>}
        {question.criteria && question.criteria.length > 0 && (
          <div><dt className="font-semibold text-muted">{t('criteriaResult')}</dt>
            <dd><ul className="grid gap-1 text-ink">{question.criteria.map((c) => (
              <li key={c.index} className="flex gap-2">
                {c.met ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-label={t('met')} /> : <XCircle className="mt-0.5 size-4 shrink-0 text-danger" aria-label={t('notMet')} />}
                <span>{c.criterion} — {t('awarded', {awarded: c.awarded, points: c.points})}</span>
              </li>
            ))}</ul></dd>
          </div>
        )}
        {objective
          ? <div><dt className="font-semibold text-muted">{t('correctAnswer')}</dt><dd className="text-ink">{show(question.question_type === 'mcq' ? question.correct_option_id ?? null : question.correct_boolean ?? null)}</dd></div>
          : <>
              <div><dt className="font-semibold text-muted">{t('modelAnswer')}</dt><dd className="text-ink">{question.model_answer}</dd></div>
              {!question.criteria?.length && <div><dt className="font-semibold text-muted">{t('rubric')}</dt><dd><ul className="list-disc pl-5 text-ink">{question.rubric?.map((c) => <li key={c.criterion}>{c.criterion} ({t('points', {count: c.points})})</li>)}</ul></dd></div>}
            </>}
        {question.explanation && <div><dt className="font-semibold text-muted">{t('why')}</dt><dd className="text-ink">{question.explanation}</dd></div>}
      </dl>
      <div className="mt-3 grid gap-2">
        {question.citations?.length ? question.citations.map((citation, i) => <CitationCard key={`${citation.chunk_id}-${i}`} citation={citation} workspaceId={workspaceId} />)
          : <p className="text-xs text-muted">{t('sourceUnavailable')}</p>}
      </div>
    </Card>
  );
}

function EvaluationBanner({attempt, workspaceId}: {attempt: QuizAttempt; workspaceId: string}) {
  const t = useTranslations('Quiz');
  const errorText = useErrorText();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  if (attempt.state === 'evaluated') {
    const percent = attempt.max_score ? Math.round((1000 * (attempt.score ?? 0)) / attempt.max_score) / 10 : 0;
    return (
      <Alert tone="success" title={t('evaluatedTitle', {score: attempt.score ?? 0, max: attempt.max_score ?? 0, percent})}
        action={attempt.report_id ? <Button asChild size="sm" variant="gradient"><Link href={`/app/w/${workspaceId}/report`}><Target />{t('openReport')}</Link></Button> : undefined}>
        {t('evaluatedBody')}
      </Alert>
    );
  }
  if (attempt.state === 'evaluation_failed') {
    const retry = async () => {
      setBusy(true);
      setMessage('');
      try {
        const next = await api<QuizAttempt>(`attempts/${attempt.id}/evaluate`, {method: 'POST'});
        client.setQueryData(keys.attempt(attempt.id), next);
        diagnosisKeys(workspaceId).forEach((queryKey) => void client.invalidateQueries({queryKey}));
      } catch (e) {
        setMessage(errorText(e));
      } finally {
        setBusy(false);
      }
    };
    const key = attempt.failure_code && t.has(`evaluationFailures.${attempt.failure_code}`) ? attempt.failure_code : 'fallback';
    return (
      <Alert tone="danger" title={t('evaluationFailedTitle')}
        action={<Button size="sm" variant="secondary" disabled={busy} onClick={() => void retry()}>{busy ? <Loader2 className="animate-spin" /> : <RotateCcw />}{t('retryEvaluation')}</Button>}>
        {t(`evaluationFailures.${key}` as 'evaluationFailures.fallback')}
        {message && <p role="alert" className="mt-1 text-danger">{message}</p>}
      </Alert>
    );
  }
  return (
    <Alert tone="info" title={<span className="inline-flex items-center gap-2"><Loader2 className="size-4 animate-spin" />{t('evaluating')}</span>}>
      <span aria-live="polite">{t('evaluatingBody')}</span>
    </Alert>
  );
}

export function QuizAttemptView({workspaceId, attemptId}: {workspaceId: string; attemptId: string}) {
  const t = useTranslations('Quiz');
  const tc = useTranslations('Common');
  const locale = useLocale();
  const errorText = useErrorText();
  const client = useQueryClient();
  const {data: attempt, isLoading, error, dataUpdatedAt} = useAttempt(attemptId, workspaceId);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, AttemptAnswer>>({});
  const [save, setSave] = useState<SaveState>('idle');
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState('');
  const timers = useRef<Record<string, number>>({});
  const pending = useRef<Set<Promise<unknown>>>(new Set());
  const {elapsed, remaining} = useAttemptClock(attempt, dataUpdatedAt);
  const locked = attempt ? attempt.state !== 'in_progress' : false;

  const [seeded, setSeeded] = useState<string | null>(null);
  if (attempt && seeded !== attempt.id + attempt.state) {
    setSeeded(attempt.id + attempt.state); // render-time sync from server data (React docs pattern)
    setAnswers(attempt.answers);
  }

  // Questions with an edit not yet sent (debounce running). "Saved" only shows when nothing is pending.
  const dirty = useRef<Set<string>>(new Set());
  const persist = useCallback((questionId: string, value: AttemptAnswer) => {
    dirty.current.delete(questionId);
    setSave('saving');
    const request: Promise<unknown> = api(`attempts/${attemptId}/responses/${questionId}`, {method: 'PUT', body: {answer: value}})
      .then(() => { if (dirty.current.size === 0 && pending.current.size <= 1) setSave('saved'); })
      .catch((e) => { setSave('error'); setMessage(errorText(e)); })
      .finally(() => pending.current.delete(request));
    pending.current.add(request);
  }, [attemptId, errorText]);

  const answer = useCallback((questionId: string, value: AttemptAnswer, immediate: boolean) => {
    setAnswers((current) => ({...current, [questionId]: value}));
    dirty.current.add(questionId);
    setSave('saving'); // never show a stale "Saved" while a debounced change is still pending
    window.clearTimeout(timers.current[questionId]);
    if (immediate) persist(questionId, value);
    else timers.current[questionId] = window.setTimeout(() => persist(questionId, value), 600);
  }, [persist]);

  const submit = useCallback(async () => {
    setSubmitting(true);
    Object.values(timers.current).forEach((id) => window.clearTimeout(id));
    try {
      await Promise.allSettled([...pending.current]);
      // Flush any typed-but-unsaved answers before locking.
      if (attempt) await Promise.allSettled(attempt.questions.filter((q) => answers[q.id] !== attempt.answers[q.id]).map((q) => api(`attempts/${attemptId}/responses/${q.id}`, {method: 'PUT', body: {answer: answers[q.id] ?? null}})));
      const result = await api<QuizAttempt>(`attempts/${attemptId}/submit`, {method: 'POST'});
      client.setQueryData(keys.attempt(attemptId), result);
      void client.invalidateQueries({queryKey: keys.quizzes(workspaceId)});
      setConfirming(false);
      window.scrollTo({top: 0});
    } catch (e) {
      setMessage(errorText(e));
    } finally {
      setSubmitting(false);
    }
  }, [answers, attempt, attemptId, client, errorText, workspaceId]);

  // Auto-submit when a timed attempt reaches zero.
  const autoSubmitted = useRef(false);
  useEffect(() => {
    if (!locked && remaining !== null && remaining <= 0 && !autoSubmitted.current) {
      autoSubmitted.current = true;
      void submit();
    }
  }, [locked, remaining, submit]);

  const question = attempt?.questions[index];
  // Keyboard: ←/→ move; A–D or 1–4 choose an option; T/F for true/false (not while typing).
  useEffect(() => {
    if (!attempt || locked || !question) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT' || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === 'ArrowRight') setIndex((i) => Math.min(attempt.questions.length - 1, i + 1));
      else if (event.key === 'ArrowLeft') setIndex((i) => Math.max(0, i - 1));
      else if (question.question_type === 'mcq') {
        const key = event.key.toUpperCase();
        const id = /^[1-4]$/.test(key) ? 'ABCD'[Number(key) - 1] : key;
        if (question.options?.some((o) => o.id === id)) answer(question.id, id, true);
      } else if (question.question_type === 'true_false' && /^[tf]$/i.test(event.key)) {
        answer(question.id, event.key.toLowerCase() === 't', true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [answer, attempt, locked, question]);

  if (isLoading) return <Skeleton className="h-96" />;
  if (error || !attempt) return <Alert tone="danger">{errorText(error)}</Alert>;

  const answered = attempt.questions.filter((q) => answers[q.id] !== undefined && answers[q.id] !== null && answers[q.id] !== '').length;

  if (locked) {
    return (
      <div className="grid gap-5">
        <Button asChild variant="ghost" size="sm" className="w-fit"><Link href={`/app/w/${workspaceId}/quiz`}><ArrowLeft />{t('backToList')}</Link></Button>
        <Alert tone="success" title={<span className="inline-flex items-center gap-2"><Lock className="size-4" />{attempt.submit_reason === 'time_limit' ? t('submittedTime') : t('submitted')}</span>}>
          {t('submittedBody', {answered, total: attempt.questions.length, time: clock(attempt.elapsed_seconds ?? 0)})}
        </Alert>
        <EvaluationBanner attempt={attempt} workspaceId={workspaceId} />
        <h2 className="text-xl">{t('reviewTitle')}</h2>
        {attempt.questions.map((q) => <ReviewItem key={q.id} question={q} answer={answers[q.id] ?? null} workspaceId={workspaceId} />)}
      </div>
    );
  }

  if (!question) return null;
  const lowTime = remaining !== null && remaining <= 60;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className="grid gap-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm font-semibold text-muted">{t('questionOf', {n: index + 1, total: attempt.questions.length})} · {question.topic_title}</p>
          <span aria-live="polite" className="text-xs text-muted">
            {save === 'saving' && <span className="inline-flex items-center gap-1"><Loader2 className="size-3 animate-spin" />{t('saving')}</span>}
            {save === 'saved' && t('saved')}
            {save === 'error' && <span className="text-danger">{t('saveFailed')}</span>}
          </span>
        </div>
        <Card className="p-5 sm:p-7">
          <Badge tone="info">{t(`types.${question.question_type}`)}</Badge>
          <h2 lang={locale} className="mt-3 text-lg font-semibold leading-relaxed tracking-normal sm:text-xl">{question.prompt}</h2>
          <div className="mt-5"><AnswerInput question={question} value={answers[question.id] ?? null} onChange={(v) => answer(question.id, v, question.question_type !== 'short_answer')} /></div>
          {question.question_type !== 'short_answer' && <p className="mt-4 text-xs text-muted">{question.question_type === 'mcq' ? t('keysMcq') : t('keysTf')}</p>}
        </Card>
        <div className="flex flex-wrap justify-between gap-3">
          <Button variant="secondary" disabled={index === 0} onClick={() => setIndex(index - 1)}><ArrowLeft />{t('previous')}</Button>
          {index < attempt.questions.length - 1
            ? <Button onClick={() => setIndex(index + 1)}>{t('next')}<ArrowRight /></Button>
            : <Button variant="gradient" onClick={() => setConfirming(true)}><Send />{t('submit')}</Button>}
        </div>
        {message && <p role="alert" className="text-sm text-danger">{message}</p>}
      </div>
      <aside className="grid h-fit gap-4 lg:sticky lg:top-24">
        <Card className={cn('p-4', lowTime && 'border-danger/40 bg-danger-50')}>
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted">
            {remaining !== null ? <Hourglass className="size-4" /> : <Clock className="size-4" />}
            {remaining !== null ? t('timeLeft') : t('elapsed')}
          </p>
          <p role="timer" aria-live={lowTime ? 'assertive' : 'off'} className={cn('mt-1 font-mono text-3xl font-bold', lowTime ? 'text-danger' : 'text-ink')}>
            {clock(remaining !== null ? remaining : elapsed)}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">{t('answeredCount', {answered, total: attempt.questions.length})}</p>
          <nav aria-label={t('navigator')} className="mt-3 grid grid-cols-5 gap-2">
            {attempt.questions.map((q, i) => {
              const done = answers[q.id] !== undefined && answers[q.id] !== null && answers[q.id] !== '';
              return (
                <button key={q.id} type="button" aria-current={i === index ? 'step' : undefined} aria-label={`${t('questionN', {n: i + 1})}${done ? ` — ${t('answered')}` : ''}`}
                  onClick={() => setIndex(i)}
                  className={cn('grid aspect-square place-items-center rounded-sm text-sm font-bold transition-colors', i === index ? 'bg-brand text-white' : done ? 'bg-pink-100 text-brand' : 'bg-soft text-muted hover:text-ink')}>
                  {i + 1}
                </button>
              );
            })}
          </nav>
          <Button variant="gradient" className="mt-4 w-full" onClick={() => setConfirming(true)}><Send />{t('submit')}</Button>
        </Card>
      </aside>
      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent title={t('confirmTitle')} closeLabel={tc('close')}>
          <p>{answered < attempt.questions.length ? t('confirmUnanswered', {count: attempt.questions.length - answered}) : t('confirmAll')}</p>
          <p className="mt-2 text-sm text-muted">{t('confirmLock')}</p>
          <div className="mt-6 flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setConfirming(false)}>{tc('cancel')}</Button>
            <Button variant="gradient" disabled={submitting} onClick={() => void submit()}>{submitting ? <Loader2 className="animate-spin" /> : <Lock />}{t('submitLock')}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
