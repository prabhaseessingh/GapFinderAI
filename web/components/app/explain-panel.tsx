'use client';

import {AlertTriangle, BookOpen, FileSearch, Image as ImageIcon, Loader2, Mic, Send, Square, Upload, Volume2} from 'lucide-react';
import {useFormatter, useLocale, useNow, useTranslations} from 'next-intl';
import {useEffect, useRef, useState, type FormEvent} from 'react';
import {Button} from '@/components/ui/button';
import {Alert, Badge, Card, Skeleton} from '@/components/ui/primitives';
import {Link, useRouter} from '@/i18n/navigation';
import {htmlLang, type AppLocale} from '@/i18n/config';
import {api, type Asset, type Explanation, type ExplanationOrigin} from '@/lib/api';
import {keys, useApiMutation, useAsset, useExplanation, useExplanations, useLimits} from '@/lib/queries';
import {cn} from '@/lib/utils';
import {CitationCard} from './citation-card';
import {useErrorText} from './shared';

const MAX_RECORDING_MS = 60_000;
const VOICE_LOCALES = new Set(['en', 'hi-IN', 'pa-IN', 'te-IN']);

function LimitChips() {
  const t = useTranslations('Explain');
  const {data} = useLimits();
  if (!data) return null;
  return (
    <ul className="flex flex-wrap gap-2" aria-label={t('limitsLabel')} data-testid="limits">
      {data.actions.filter((a) => a.action !== 'diagnostic').map((a) => (
        <li key={a.action}><Badge tone={a.used >= a.limit ? 'danger' : 'neutral'}>{t(`limits.${a.action}`, {left: a.limit - a.used, limit: a.limit})}</Badge></li>
      ))}
    </ul>
  );
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function MicButton({workspaceId, onText, disabledReason}: {workspaceId: string; onText: (text: string) => void; disabledReason: string | null}) {
  const t = useTranslations('Explain');
  const locale = useLocale();
  const errorText = useErrorText();
  const client = useApiMutation((body: Record<string, unknown>) => api<{text: string}>('voice/transcribe', {method: 'POST', body}), () => [keys.limits]);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => () => { window.clearTimeout(timer.current); recorder.current?.stream.getTracks().forEach((track) => track.stop()); }, []);

  async function start() {
    setError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      const type = ['audio/webm', 'audio/mp4', 'audio/ogg'].find((m) => MediaRecorder.isTypeSupported(m)) ?? '';
      const rec = new MediaRecorder(stream, type ? {mimeType: type} : undefined);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        const blob = new Blob(chunks, {type: rec.mimeType || 'audio/webm'});
        if (blob.size > 2 * 1024 * 1024) return setError(t('recordingTooLong'));
        try {
          const result = await client.mutateAsync({workspace_id: workspaceId, locale, mime_type: blob.type.split(';')[0], audio_base64: await blobToBase64(blob)});
          onText(result.text);
        } catch (e) {
          setError(errorText(e));
        }
      };
      recorder.current = rec;
      rec.start();
      setRecording(true);
      timer.current = window.setTimeout(() => rec.state === 'recording' && rec.stop(), MAX_RECORDING_MS);
    } catch {
      setError(t('micDenied'));
    }
  }
  function stop() {
    window.clearTimeout(timer.current);
    if (recorder.current?.state === 'recording') recorder.current.stop();
  }
  if (disabledReason) {
    return <p className="text-xs text-muted"><Mic className="mr-1 inline size-3.5" />{disabledReason}</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button type="button" variant={recording ? 'primary' : 'secondary'} size="sm" disabled={client.isPending} aria-pressed={recording}
        onClick={() => (recording ? stop() : void start())}>
        {client.isPending ? <Loader2 className="animate-spin" /> : recording ? <Square /> : <Mic />}
        {client.isPending ? t('transcribing') : recording ? t('stopRecording') : t('speak')}
      </Button>
      {recording && <span className="text-xs font-semibold text-danger" aria-live="polite">{t('recording')}</span>}
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
    </div>
  );
}

function AskForm({workspaceId, initialQuestion, topicId, origin, onAsked, voiceReason}: {
  workspaceId: string; initialQuestion: string; topicId: string | null; origin: ExplanationOrigin;
  onAsked: (id: string) => void; voiceReason: string | null;
}) {
  const t = useTranslations('Explain');
  const locale = useLocale();
  const errorText = useErrorText();
  const [question, setQuestion] = useState(initialQuestion);
  const [source, setSource] = useState<ExplanationOrigin>(origin);
  const [error, setError] = useState('');
  const ask = useApiMutation((body: Record<string, unknown>) => api<Explanation>('explanations', {method: 'POST', body}),
    () => [keys.explanations(workspaceId), keys.limits]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    try {
      const created = await ask.mutateAsync({workspace_id: workspaceId, question: question.trim(), locale, topic_id: topicId, origin: source});
      onAsked(created.id);
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <Card className="p-5">
      <form onSubmit={submit} className="grid gap-3" aria-label={t('askLabel')}>
        <label htmlFor="explain-question" className="text-sm font-semibold text-ink">{t('questionLabel')}</label>
        <textarea id="explain-question" value={question} onChange={(e) => { setQuestion(e.target.value); if (source === 'voice') setSource('typed'); }}
          rows={3} maxLength={1000} placeholder={t('placeholder')}
          className="w-full rounded-sm border border-line-strong bg-surface p-3.5 text-[15px] text-ink focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15" />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <MicButton workspaceId={workspaceId} disabledReason={voiceReason} onText={(text) => { setQuestion(text); setSource('voice'); }} />
          <Button type="submit" variant="gradient" disabled={ask.isPending || question.trim().length < 3}>
            {ask.isPending ? <Loader2 className="animate-spin" /> : <Send />}{t('ask')}
          </Button>
        </div>
        <p className="text-xs text-muted">{t('groundedNote')}</p>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      </form>
    </Card>
  );
}

function AssetView({asset}: {asset: Asset}) {
  const t = useTranslations('Explain');
  const {data} = useAsset(asset.id, asset.state);
  const current = data ?? asset;
  if (current.state === 'queued' || current.state === 'rendering') {
    return <p className="flex items-center gap-2 text-sm text-muted" aria-live="polite"><Loader2 className="size-4 animate-spin" />{t(current.kind === 'audio' ? 'renderingAudio' : 'renderingImage')}</p>;
  }
  if (current.state === 'not_eligible') return <p className="text-sm text-muted">{t('notVisualizable')}</p>;
  if (current.state === 'failed') {
    return <Alert tone="warning">{t(current.kind === 'audio' ? 'audioFailed' : 'imageFailed')}</Alert>;
  }
  if (!current.url) return <p className="text-sm text-muted">{t('assetUnavailable')}</p>;
  if (current.kind === 'audio') {
    return <audio controls src={current.url} className="w-full" aria-label={t('audioLabel')} data-testid="explain-audio" />;
  }
  if (current.kind === 'source_figure') {
    return (
      <div className="rounded-sm bg-pink-50 px-3 py-2 text-sm">
        <p className="font-semibold text-ink">{t('sourceFigure', {document: String(current.meta.document_name ?? ''), page: Number(current.meta.page ?? 1)})}</p>
        <a href={current.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-brand hover:underline"><FileSearch className="size-3.5" />{t('openFigure')}</a>
      </div>
    );
  }
  return (
    <figure className="grid gap-2" data-testid="explain-illustration">
      {/* eslint-disable-next-line @next/next/no-img-element -- short-lived signed URL from private storage */}
      <img src={current.url} alt={t('illustrationAlt', {title: String(current.meta.title ?? '')})} className="w-full max-w-md rounded-md border border-line" />
      {Array.isArray(current.meta.elements) && current.meta.elements.length > 0 && (
        <p className="text-sm text-ink">{t('illustrationShows', {items: (current.meta.elements as string[]).join(' · ')})}</p>
      )}
      <figcaption className="flex items-start gap-2 text-xs text-muted"><AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />{t('aiLabel')}</figcaption>
    </figure>
  );
}

function ExplanationView({id, workspaceId}: {id: string; workspaceId: string}) {
  const t = useTranslations('Explain');
  const locale = useLocale() as AppLocale;
  const errorText = useErrorText();
  const {data, isLoading, error} = useExplanation(id, locale);
  const [actionError, setActionError] = useState('');
  const requestAsset = useApiMutation((kind: 'audio' | 'visual') => api<Asset>(`explanations/${id}/${kind}`, {method: 'POST'}),
    () => [keys.explanation(id, locale), keys.limits]);
  if (isLoading) return <Skeleton className="h-64" />;
  if (error || !data) return <Alert tone="danger">{errorText(error)}</Alert>;
  const run = async (kind: 'audio' | 'visual') => {
    setActionError('');
    try { await requestAsset.mutateAsync(kind); } catch (e) { setActionError(errorText(e)); }
  };
  const audio = data.assets.filter((a) => a.kind === 'audio').at(-1);
  const visual = data.assets.filter((a) => a.kind !== 'audio').at(-1);
  return (
    <Card className="grid gap-4 p-5" data-testid="explanation">
      <p className="text-sm font-semibold text-muted">{data.question}</p>
      {(data.state === 'queued' || data.state === 'running') && (
        <p className="flex items-center gap-2 text-sm text-ink" aria-live="polite"><Loader2 className="size-4 animate-spin text-brand" />{t('thinking')}</p>
      )}
      {data.state === 'insufficient' && (
        <Alert tone="info" title={t('insufficientTitle')} action={<Button asChild size="sm" variant="secondary"><Link href={`/app/w/${workspaceId}/materials`}><Upload />{t('uploadMaterial')}</Link></Button>}>
          {t('insufficientBody')}
        </Alert>
      )}
      {data.state === 'failed' && (
        <Alert tone="danger" title={t('failedTitle')}>
          {data.failure_code && t.has(`failures.${data.failure_code.split(':')[0]}`) ? t(`failures.${data.failure_code.split(':')[0]}` as 'failures.fallback') : t('failures.fallback')}
        </Alert>
      )}
      {data.state === 'answered' && data.answer && (
        <>
          <div lang={htmlLang(data.locale as AppLocale)} className="grid gap-3 text-[15px] leading-relaxed text-ink" data-testid="explanation-answer">
            {data.answer.split(/\n{2,}/).map((paragraph, i) => <p key={i}>{paragraph}</p>)}
          </div>
          <div className="grid gap-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted"><BookOpen className="size-4" />{t('sources')}</h3>
            {data.citations.length ? data.citations.map((c, i) => (
              <div key={`${c.chunk_id}-${i}`} className="grid gap-1">
                <CitationCard citation={c} workspaceId={workspaceId} />
                {c.translated_quote && <p lang={htmlLang(locale)} className="border-l-[3px] border-line-strong px-3 text-sm text-text"><span className="font-semibold">{t('translation')}: </span>{c.translated_quote}</p>}
              </div>
            )) : <p className="text-xs text-muted">{t('sourceUnavailable')}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" disabled={!data.voice_available || requestAsset.isPending || Boolean(audio && audio.state !== 'failed')} onClick={() => void run('audio')}>
              <Volume2 />{t('listen')}
            </Button>
            <Button size="sm" variant="secondary" disabled={!data.visual_available || requestAsset.isPending || Boolean(visual && visual.state !== 'failed')} onClick={() => void run('visual')}>
              <ImageIcon />{t('illustrate')}
            </Button>
          </div>
          {!data.voice_available && data.voice_reason && <p className="text-xs text-muted">{t(`voiceReasons.${data.voice_reason}` as 'voiceReasons.not_configured')}</p>}
          {data.visual_reason === 'source_figure_only' && <p className="text-xs text-muted">{t('visualSourceOnly')}</p>}
          {actionError && <p role="alert" className="text-sm text-danger">{actionError}</p>}
          {audio && <AssetView asset={audio} />}
          {visual && <AssetView asset={visual} />}
        </>
      )}
    </Card>
  );
}

export function ExplainPanel({workspaceId, question = '', topicId = null, origin = 'typed'}: {
  workspaceId: string; question?: string; topicId?: string | null; origin?: ExplanationOrigin;
}) {
  const t = useTranslations('Explain');
  const locale = useLocale();
  const format = useFormatter();
  const now = useNow({updateInterval: 60_000});
  const router = useRouter();
  const {data: history, isLoading} = useExplanations(workspaceId);
  const [selected, setSelected] = useState<string | null>(null);
  const current = selected ?? (question ? null : history?.[0]?.id ?? null);
  const voiceReason = VOICE_LOCALES.has(locale) ? null : t('voiceReasons.language_unsupported');
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl">{t('title')}</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">{t('subtitle')}</p>
        </div>
        <LimitChips />
      </div>
      <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="order-2 lg:order-1">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-muted">{t('history')}</h3>
          {isLoading && <Skeleton className="mt-2 h-24" />}
          {history?.length === 0 && <p className="mt-2 text-sm text-muted">{t('noHistory')}</p>}
          <ul className="mt-2 grid gap-1.5">
            {history?.map((item) => (
              <li key={item.id}>
                <button type="button" onClick={() => setSelected(item.id)} aria-current={item.id === current ? 'true' : undefined}
                  className={cn('w-full rounded-sm px-3 py-2 text-left text-sm transition-colors', item.id === current ? 'bg-pink-50 text-brand' : 'text-ink hover:bg-soft')}>
                  <span className="line-clamp-2 font-semibold">{item.question}</span>
                  <span className="text-xs text-muted">{format.relativeTime(new Date(item.created_at), now)}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <div className="order-1 grid gap-5 lg:order-2">
          <AskForm key={`${topicId}-${question}`} workspaceId={workspaceId} initialQuestion={question} topicId={topicId} origin={origin} voiceReason={voiceReason}
            onAsked={(id) => { setSelected(id); if (question) router.replace(`/app/w/${workspaceId}/explain`); }} />
          {current && <ExplanationView key={current} id={current} workspaceId={workspaceId} />}
        </div>
      </div>
    </div>
  );
}
