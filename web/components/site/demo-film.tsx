'use client';

import {ArrowRight, BookOpen, CalendarCheck, CalendarDays, CheckCircle2, CircleDashed, ClipboardCheck, Clock, FileQuestion, FileStack, FileText, FolderOpen, LineChart, MessageCircleQuestion, Network, NotebookPen, Pause, Play, Quote, RotateCcw, ScrollText, Send, Target, UploadCloud, Volume2} from 'lucide-react';
import {AnimatePresence, animate, motion, useInView, useReducedMotion} from 'framer-motion';
import {useFormatter, useLocale, useTranslations} from 'next-intl';
import {useEffect, useRef, useState, type ReactNode, type RefObject} from 'react';
import {LogoMark} from '@/components/brand/logo';
import {LabelBadge} from '@/components/app/gap-report';
import {PIPELINE, PipelineSteps, StateBadge} from '@/components/app/shared';
import {Badge} from '@/components/ui/primitives';
import {Link} from '@/i18n/navigation';
import type {DocumentState} from '@/lib/api';
import {showcaseCitation, showcaseExplanation, showcaseQuestion, showcaseSessions, showcaseTopics, showcaseUnits} from '@/lib/showcase';
import {cn} from '@/lib/utils';

/**
 * A scripted, video-style walkthrough shown on the hero laptop: the problem, then the core flow
 * (upload → topic map → diagnostic → Gap Report → plan → Explain) with a mouse cursor, clicks and captions.
 * Drawn at a fixed 960×600 "screen" and scaled to fit. Every scene is a pure function of its elapsed time,
 * so seeking, replay and reduced motion (finished state, no autoplay) are trivial.
 */
const W = 960;
const H = 600;
const BAR_H = 36;
const WORKSPACE = 'Class 10 Science';

type Tap = {at: number; target: string};
type SceneId = 'problem' | 'upload' | 'topics' | 'quiz' | 'report' | 'plan' | 'explain' | 'outro';
const SCENES: {id: SceneId; duration: number; taps: Tap[]}[] = [
  {id: 'problem', duration: 7200, taps: []},
  {id: 'upload', duration: 6800, taps: [{at: 1300, target: 'role'}, {at: 2500, target: 'drop'}]},
  {id: 'topics', duration: 7200, taps: [{at: 1700, target: 'topic-e1'}, {at: 4200, target: 'approve'}]},
  {id: 'quiz', duration: 6200, taps: [{at: 1700, target: 'optB'}, {at: 3500, target: 'submit'}]},
  {id: 'report', duration: 6600, taps: [{at: 3500, target: 'unit0'}]},
  {id: 'plan', duration: 6000, taps: [{at: 2700, target: 'check0'}]},
  {id: 'explain', duration: 8400, taps: [{at: 1900, target: 'ask'}, {at: 5600, target: 'listen'}]},
  {id: 'outro', duration: 5600, taps: []}
];
const STEPS = ['upload', 'topics', 'quiz', 'report', 'plan', 'explain'] as const;
type StepId = (typeof STEPS)[number];
const TOTAL = SCENES.reduce((sum, s) => sum + s.duration, 0);
const END = Number.POSITIVE_INFINITY;

const clamp = (v: number) => Math.min(1, Math.max(0, v));
const progress = (t: number, from: number, to: number) => clamp((t - from) / (to - from));
const ease = (v: number) => 1 - Math.pow(1 - v, 3);
const clockText = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;

/* ---------------- player ---------------- */
export function DemoFilm() {
  const t = useTranslations('Home');
  const reduce = useReducedMotion();
  const wrapRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);
  const inView = useInView(wrapRef, {amount: 0.3});
  const [scale, setScale] = useState(0);
  const [clock, setClock] = useState({scene: 0, t: 0});
  const [playing, setPlaying] = useState(true);
  const running = playing && inView && !reduce;

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const observer = new ResizeObserver(() => setScale(wrap.clientWidth / W));
    observer.observe(wrap);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!running) return;
    let last = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const dt = Math.min(100, now - last);
      last = now;
      setClock(({scene, t: elapsed}) => {
        const next = elapsed + dt;
        return next >= SCENES[scene].duration ? {scene: (scene + 1) % SCENES.length, t: 0} : {scene, t: next};
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [running]);

  const def = SCENES[clock.scene];
  const time = reduce ? END : clock.t;
  const seek = (scene: number) => setClock({scene, t: 0});
  const elapsedTotal = SCENES.slice(0, clock.scene).reduce((sum, s) => sum + s.duration, 0) + clock.t;

  return (
    <div ref={wrapRef} className="relative w-full overflow-hidden" style={{aspectRatio: `${W} / ${H}`}}>
      <div className="absolute left-0 top-0 origin-top-left" style={{width: W, height: H, transform: `scale(${scale})`, visibility: scale ? 'visible' : 'hidden'}}>
        <div ref={sceneRef} className="absolute inset-x-0 top-0 overflow-hidden" style={{height: H - BAR_H}}>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={def.id} className="absolute inset-0"
              initial={reduce ? false : {opacity: 0}} animate={{opacity: 1}} exit={reduce ? undefined : {opacity: 0}} transition={{duration: 0.3}}>
              <Scene id={def.id} t={time} onReplay={() => seek(0)} />
            </motion.div>
          </AnimatePresence>
          <Caption id={def.id} t={time} />
          {!reduce && <Cursor taps={def.taps} t={clock.t} sceneKey={def.id} rootRef={sceneRef} />}
        </div>

        {/* video-style control bar */}
        <div className="absolute inset-x-0 bottom-0 flex items-center gap-3 bg-[#14162a] px-3 text-white" style={{height: BAR_H}}>
          <button type="button" disabled={Boolean(reduce)} onClick={() => setPlaying(!playing)} aria-label={playing ? t('tourPause') : t('tourPlay')}
            className="grid size-7 shrink-0 place-items-center rounded-full bg-white/10 hover:bg-white/20 disabled:opacity-40">
            {playing && !reduce ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
          </button>
          <div className="flex flex-1 gap-1">
            {SCENES.map((scene, i) => (
              <button key={scene.id} type="button" onClick={() => seek(i)} aria-label={sceneLabel(t, scene.id)} aria-current={i === clock.scene}
                className="group flex h-5 flex-1 items-center" style={{flexGrow: scene.duration}}>
                <span className="block h-1 w-full overflow-hidden rounded-full bg-white/20 transition-[height] group-hover:h-1.5">
                  <span className="block h-full rounded-full bg-brand-gradient-vivid"
                    style={{width: `${i < clock.scene ? 100 : i === clock.scene ? (reduce ? 100 : (clock.t / scene.duration) * 100) : 0}%`}} />
                </span>
              </button>
            ))}
          </div>
          <span className="shrink-0 font-mono text-[11px] tabular-nums text-white/70">{clockText(reduce ? TOTAL : elapsedTotal)} / {clockText(TOTAL)}</span>
        </div>
      </div>
    </div>
  );
}

function sceneLabel(t: ReturnType<typeof useTranslations<'Home'>>, id: SceneId) {
  if (id === 'problem') return t('film.problem3');
  if (id === 'outro') return t('film.outro');
  return t(`film.${id}`);
}

/* ---------------- mouse cursor ---------------- */
function Cursor({taps, t, sceneKey, rootRef}: {taps: Tap[]; t: number; sceneKey: string; rootRef: RefObject<HTMLDivElement | null>}) {
  const active = taps.find((tap) => t >= tap.at - 1100 && t < tap.at + 600);
  const key = active ? `${sceneKey}:${active.target}` : null;
  const cursorRef = useRef<HTMLDivElement>(null);
  const placed = useRef(false);

  useEffect(() => {
    if (!active) { placed.current = false; return; }
    const root = rootRef.current;
    const cursor = cursorRef.current;
    const el = root?.querySelector<HTMLElement>(`[data-tap="${active.target}"]`);
    if (!root || !el || !cursor) return;
    // Layout offsets, not screen rects: the laptop is scaled and tilted in 3D, which would skew a rect.
    let tx = el.offsetWidth / 2;
    let ty = el.offsetHeight / 2;
    let node: HTMLElement | null = el;
    while (node && node !== root) { tx += node.offsetLeft; ty += node.offsetTop; node = node.offsetParent as HTMLElement | null; }
    if (node !== root) return;
    const from = placed.current ? {} : {x: [tx + 140, tx], y: [ty + 90, ty]};
    placed.current = true;
    const move = animate(cursor, {x: tx, y: ty, ...from}, {duration: 0.8, ease: [0.22, 1, 0.36, 1]});
    return () => move.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const pressed = active ? t >= active.at && t < active.at + 200 : false;
  const clicked = active ? t >= active.at : false;
  return (
    <AnimatePresence>
      {active && (
        <motion.div ref={cursorRef} key="cursor" aria-hidden className="pointer-events-none absolute left-0 top-0 z-40"
          initial={{opacity: 0}} animate={{opacity: 1}} exit={{opacity: 0}} transition={{duration: 0.2}}>
          {clicked && (
            <motion.span key={key} className="absolute -left-5 -top-5 size-10 rounded-full border-2 border-brand bg-brand/20"
              initial={{scale: 0.2, opacity: 1}} animate={{scale: 1.5, opacity: 0}} transition={{duration: 0.55, ease: 'easeOut'}} />
          )}
          <motion.svg viewBox="0 0 24 24" className="absolute -left-[3px] -top-[2px] size-6 drop-shadow-[0_3px_6px_rgba(20,22,42,.35)]"
            animate={{scale: pressed ? 0.82 : 1}} transition={{duration: 0.1}} style={{transformOrigin: '3px 2px'}}>
            <path d="M3 2l15.5 9.2-6.6 1.4 3.9 7.4-2.9 1.5-3.9-7.4L4.4 18.8Z" fill="#14162a" stroke="#fff" strokeWidth="1.5" strokeLinejoin="round" />
          </motion.svg>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ---------------- captions ---------------- */
function Caption({id, t}: {id: SceneId; t: number}) {
  const tf = useTranslations('Home');
  const step = STEPS.indexOf(id as StepId);
  if (step < 0) return null;
  const on = t > 300;
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-4 z-30 flex justify-center">
      <motion.p key={id} initial={{opacity: 0, y: 12}} animate={{opacity: on ? 1 : 0, y: on ? 0 : 12}} transition={{duration: 0.35}}
        className="flex items-center gap-2.5 rounded-full bg-ink/90 py-2 pl-2 pr-5 text-white shadow-float backdrop-blur">
        <span className="rounded-full bg-brand-gradient px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em]">{tf('film.step', {n: step + 1, total: STEPS.length})}</span>
        <span className="text-[15px] font-bold">{tf(`film.${id as StepId}`)}</span>
      </motion.p>
    </div>
  );
}

/* ---------------- shared bits ---------------- */
function Scene({id, t, onReplay}: {id: SceneId; t: number; onReplay: () => void}) {
  switch (id) {
    case 'problem': return <ProblemScene t={t} />;
    case 'upload': return <UploadScene t={t} />;
    case 'topics': return <TopicsScene t={t} />;
    case 'quiz': return <QuizScene t={t} />;
    case 'report': return <ReportScene t={t} />;
    case 'plan': return <PlanScene t={t} />;
    case 'explain': return <ExplainScene t={t} />;
    default: return <OutroScene onReplay={onReplay} />;
  }
}

function Show({when, children, className, y = 10}: {when: boolean; children: ReactNode; className?: string; y?: number}) {
  return (
    <motion.div className={className} initial={false} animate={{opacity: when ? 1 : 0, y: when ? 0 : y}} transition={{duration: 0.4, ease: [0.22, 1, 0.36, 1]}}>
      {children}
    </motion.div>
  );
}

function Panel({children, className}: {children: ReactNode; className?: string}) {
  return <div className={cn('rounded-lg border border-line bg-surface p-4 shadow-card', className)}>{children}</div>;
}

const TABS = [
  {slug: 'materials', icon: FileStack},
  {slug: 'topics', icon: Network},
  {slug: 'quiz', icon: ClipboardCheck},
  {slug: 'report', icon: Target},
  {slug: 'plan', icon: CalendarDays},
  {slug: 'progress', icon: LineChart},
  {slug: 'explain', icon: MessageCircleQuestion}
] as const;

/** Desktop app chrome, as in the real app: header, workspace title and section tabs. */
function AppScreen({active, children}: {active: (typeof TABS)[number]['slug']; children: ReactNode}) {
  const tw = useTranslations('Workspace');
  const tl = useTranslations('Locale');
  const locale = useLocale();
  return (
    <div className="flex h-full flex-col bg-canvas">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-6">
        <LogoMark className="size-7" />
        <span className="text-[15px] font-extrabold tracking-display text-ink">GapFinder<span className="text-brand-gradient"> AI</span></span>
        <span className="h-5 w-px bg-line" />
        <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-ink"><FolderOpen className="size-3.5 text-brand" />{WORKSPACE}</span>
        <span className="ml-auto rounded-md border border-line px-3 py-1 text-[11px] text-ink">{tl(locale as 'en')}</span>
      </header>
      <div className="shrink-0 px-6 pt-3">
        <p className="text-[22px] font-extrabold tracking-display text-ink">{WORKSPACE}</p>
        <nav className="mt-1 flex gap-1 border-b border-line">
          {TABS.map(({slug, icon: Icon}) => (
            <span key={slug} className={cn('relative flex items-center gap-1.5 px-3 py-2 text-[12px] font-semibold', slug === active ? 'text-brand' : 'text-muted')}>
              <Icon className="size-3.5" />{tw(slug)}
              {slug === active && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-gradient-vivid" />}
            </span>
          ))}
        </nav>
      </div>
      <div className="relative min-h-0 flex-1 px-6 pt-4">{children}</div>
    </div>
  );
}

function Importance({value}: {value: number}) {
  return (
    <span className="flex shrink-0 gap-0.5" aria-hidden>
      {[1, 2, 3, 4, 5].map((level) => <span key={level} className={cn('h-3 w-1.5 rounded-full', level <= value ? 'bg-brand-gradient-vivid' : 'bg-soft')} />)}
    </span>
  );
}

/* ---------------- scenes ---------------- */
const PILE = [
  {name: 'chapter-12-electricity.pdf', r: -6, x: 10, y: 0},
  {name: 'class-notes-week3.docx', r: 4, x: 90, y: 56},
  {name: 'board-paper-2024.pdf', r: -3, x: 0, y: 112},
  {name: 'life-processes.pdf', r: 6, x: 100, y: 168},
  {name: 'revision-notes.txt', r: -5, x: 20, y: 224},
  {name: 'sample-paper-2025.pdf', r: 3, x: 80, y: 280}
];

function ProblemScene({t}: {t: number}) {
  const tf = useTranslations('Home');
  const reveal = t >= 4600;
  return (
    <div className="relative h-full overflow-hidden bg-[#14162a] text-white">
      <span aria-hidden className="absolute -right-24 -top-24 size-96 rounded-full bg-brand/35 blur-3xl" />
      <span aria-hidden className="absolute -bottom-32 -left-24 size-96 rounded-full bg-amber/20 blur-3xl" />
      <AnimatePresence mode="wait" initial={false}>
        {!reveal ? (
          <motion.div key="problem" exit={{opacity: 0, scale: 0.97}} transition={{duration: 0.35}} className="relative grid h-full grid-cols-[1.1fr_1fr] items-center gap-6 px-16">
            <div className="grid gap-4">
              <Show when={t >= 200}><p className="text-[34px] font-extrabold leading-[1.15] tracking-display">{tf('film.problem1')}</p></Show>
              <Show when={t >= 1300}><p className="text-[34px] font-extrabold leading-[1.15] tracking-display text-white/65">{tf('film.problem2')}</p></Show>
              <Show when={t >= 2600}><p className="text-[34px] font-extrabold leading-[1.15] tracking-display"><span className="text-brand-gradient">{tf('film.problem3')}</span></p></Show>
            </div>
            <div className="relative h-[330px]">
              {PILE.map((doc, i) => (
                <motion.div key={doc.name} className="absolute flex w-60 items-center gap-2.5 rounded-lg bg-white/95 px-3 py-2.5 text-ink shadow-float"
                  style={{left: doc.x, top: doc.y}} initial={false}
                  animate={t >= 1400 + i * 180 ? {opacity: 1, rotate: doc.r, y: 0} : {opacity: 0, rotate: 0, y: -40}}
                  transition={{type: 'spring', stiffness: 260, damping: 20}}>
                  <span className="grid size-8 place-items-center rounded-md bg-pink-100 text-brand"><FileText className="size-4" /></span>
                  <span className="truncate text-[12px] font-semibold">{doc.name}</span>
                </motion.div>
              ))}
            </div>
          </motion.div>
        ) : (
          <motion.div key="reveal" initial={{opacity: 0, scale: 0.92}} animate={{opacity: 1, scale: 1}} transition={{duration: 0.5, ease: [0.22, 1, 0.36, 1]}}
            className="relative flex h-full flex-col items-center justify-center text-center">
            <LogoMark className="size-20 drop-shadow-[0_12px_36px_rgba(236,0,140,.5)]" />
            <p className="mt-5 text-[38px] font-extrabold tracking-display">GapFinder<span className="text-brand-gradient"> AI</span></p>
            <p className="mt-2 max-w-md text-[17px] text-white/75">{tf('film.revealBody')}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

const ROLE_ICONS = [{role: 'syllabus', icon: ScrollText}, {role: 'textbook', icon: BookOpen}, {role: 'notes', icon: NotebookPen}, {role: 'past_paper', icon: FileQuestion}] as const;
const pipelineAt = (t: number, start: number, step = 380): DocumentState =>
  t < start ? 'scanning' : PIPELINE[Math.min(PIPELINE.length - 1, Math.floor((t - start) / step))];

function UploadScene({t}: {t: number}) {
  const tm = useTranslations('Materials');
  const files = [
    {name: 'science-syllabus.pdf', role: 'syllabus' as const, start: 2700},
    {name: 'class10-science-notes.docx', role: 'notes' as const, start: 3200},
    {name: 'board-paper-2025-scan.pdf', role: 'past_paper' as const, start: 3700}
  ];
  return (
    <AppScreen active="materials">
      <div className="grid grid-cols-[320px_1fr] gap-5">
        <Panel>
          <p className="text-[16px] font-extrabold tracking-display text-ink">{tm('title')}</p>
          <p className="mt-0.5 text-[11px] text-muted">{tm('subtitle')}</p>
          <p className="mt-3 text-[11px] font-bold text-ink">{tm('role')}</p>
          <div className="mt-1.5 grid grid-cols-2 gap-1.5">
            {ROLE_ICONS.map(({role, icon: Icon}) => {
              const selected = role === 'syllabus' && t >= 1300;
              return (
                <span key={role} data-tap={role === 'syllabus' ? 'role' : undefined}
                  className={cn('flex items-center gap-1.5 rounded-md border px-2.5 py-2 text-[11px] font-semibold transition-colors duration-200', selected ? 'border-brand bg-pink-50 text-brand' : 'border-line bg-surface text-ink')}>
                  <Icon className="size-3.5 shrink-0" />{tm(`roles.${role}`)}
                </span>
              );
            })}
          </div>
          <motion.div data-tap="drop" animate={{scale: t >= 2500 && t < 2700 ? 0.97 : 1}}
            className={cn('mt-3 grid place-items-center rounded-lg border-2 border-dashed px-3 py-4 text-center transition-colors', t >= 2500 ? 'border-brand/50 bg-pink-50' : 'border-line-strong bg-canvas')}>
            <UploadCloud className="size-6 text-plum" />
            <p className="mt-1 text-[11px] font-semibold text-ink">{tm.rich('drop', {browse: (chunks) => <span className="text-brand underline">{chunks}</span>})}</p>
            <p className="mt-0.5 text-[9.5px] text-muted">{tm('dropHint')}</p>
          </motion.div>
        </Panel>
        <div>
          <p className="text-[16px] font-extrabold tracking-display text-ink">{tm('listTitle')}</p>
          <div className="mt-2 grid gap-2">
            {files.map((file) => {
              const state = pipelineAt(t, file.start + 300);
              const Icon = ROLE_ICONS.find((r) => r.role === file.role)!.icon;
              return (
                <Show key={file.name} when={t >= file.start}>
                  <div className="flex items-center gap-3 rounded-md border border-line bg-surface p-3">
                    <span className="grid size-9 shrink-0 place-items-center rounded-sm bg-pink-100 text-brand"><Icon className="size-4" /></span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12.5px] font-semibold text-ink">{file.name}</p>
                      <p className="text-[10px] text-muted">{tm(`roles.${file.role}`)}</p>
                    </div>
                    <PipelineSteps state={state} />
                    <span className="w-28 text-right"><StateBadge state={state} /></span>
                  </div>
                </Show>
              );
            })}
          </div>
        </div>
      </div>
    </AppScreen>
  );
}

function TopicsScene({t}: {t: number}) {
  const tt = useTranslations('Topics');
  const tc = useTranslations('Common');
  const approvedAt = (i: number) => 4350 + i * 110;
  const approved = showcaseTopics.filter((_, i) => t >= approvedAt(i)).length;
  const evidence = t >= 1700;
  const e1 = showcaseTopics.find((topic) => topic.id === 'e1')!;
  return (
    <AppScreen active="topics">
      <div className="grid grid-cols-[1fr_300px] gap-5">
        <div>
          <div className="flex items-center gap-3">
            <p className="text-[16px] font-extrabold tracking-display text-ink">{tt('title')}</p>
            <Badge tone={approved === showcaseTopics.length ? 'success' : 'neutral'}>{tt('summary', {approved, total: showcaseTopics.length})}</Badge>
            <motion.span data-tap="approve" animate={{scale: t >= 4200 && t < 4400 ? 0.95 : 1}}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-brand-gradient px-3 py-1.5 text-[11.5px] font-bold text-white shadow-glow-sm">
              <CheckCircle2 className="size-3.5" />{tt('approveAll')}
            </motion.span>
          </div>
          <div className="mt-2.5 grid gap-1.5">
            {showcaseTopics.map((topic, i) => {
              const done = t >= approvedAt(i);
              const selected = topic.id === 'e1' && evidence;
              return (
                <Show key={topic.id} when={t >= 200 + i * 220} y={6}>
                  <div data-tap={`topic-${topic.id}`}
                    className={cn('flex items-center gap-2.5 rounded-md border bg-surface px-3 py-1.5 transition-colors duration-300', topic.parent_id && 'ml-6', selected ? 'border-brand shadow-card' : done ? 'border-success/30' : 'border-line')}>
                    {done ? <CheckCircle2 className="size-4 shrink-0 text-success" /> : <CircleDashed className="size-4 shrink-0 text-muted" />}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12px] font-semibold text-ink">{topic.title}</p>
                      <p className="flex items-center gap-1 text-[9.5px] text-plum"><Quote className="size-3" />{tt('citations', {count: topic.citation_count})}</p>
                    </div>
                    <Importance value={topic.importance} />
                    <span className="w-20 text-right"><Badge tone={done ? 'success' : 'neutral'}>{tt(done ? 'approved' : 'draft')}</Badge></span>
                  </div>
                </Show>
              );
            })}
          </div>
        </div>
        <AnimatePresence mode="wait" initial={false}>
          {evidence ? (
            <motion.div key="evidence" initial={{opacity: 0, x: 16}} animate={{opacity: 1, x: 0}} transition={{duration: 0.4}}>
              <Panel>
                <p className="text-[13px] font-extrabold tracking-display text-ink">{tt('evidenceTitle', {title: e1.title})}</p>
                <p className="mt-0.5 text-[10px] text-muted">{tt('evidenceSubtitle')}</p>
                <div className="mt-3 rounded-md border border-line p-2.5">
                  <p className="flex items-center gap-1 text-[10px] font-semibold text-muted"><Quote className="size-3 text-plum" />{showcaseCitation.file} · {tc('page', {page: showcaseCitation.page})}</p>
                  <p className="mt-0.5 text-[9.5px] text-muted">{showcaseCitation.heading}</p>
                  <p className="mt-1.5 border-l-2 border-brand bg-pink-50 px-2 py-1.5 text-[11px] leading-snug text-ink">“{showcaseCitation.quote}”</p>
                  <Show when={t >= 2600}>
                    <p className="mt-2 text-[9px] font-semibold text-plum">{tt('translation', {language: 'हिन्दी'})}</p>
                    <p className="mt-0.5 text-[11px] leading-snug text-text" lang="hi">{showcaseCitation.translation}</p>
                  </Show>
                </div>
              </Panel>
            </motion.div>
          ) : (
            <motion.div key="hint" exit={{opacity: 0}} className="grid h-40 place-items-center rounded-lg border-2 border-dashed border-line text-center text-[11px] text-muted">
              <span className="flex flex-col items-center gap-1"><Quote className="size-5 text-plum" />{tt('viewEvidence')}</span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </AppScreen>
  );
}

function QuizScene({t}: {t: number}) {
  const tq = useTranslations('Quiz');
  const picked = t >= 1700;
  const submitted = t >= 3600;
  const seconds = 14 + Math.floor(Math.min(t, 3600) / 1000);
  return (
    <AppScreen active="quiz">
      <div className="grid grid-cols-[1fr_220px] gap-5">
        <div>
          <p className="text-[11px] font-semibold text-muted">{tq('questionOf', {n: 2, total: 5})} · {showcaseQuestion.topic_title}</p>
          <Panel className="mt-2">
            <Badge tone="info">{tq(`types.${showcaseQuestion.question_type}`)}</Badge>
            <p className="mt-2 text-[15px] font-semibold leading-snug text-ink">{showcaseQuestion.prompt}</p>
            <div className="mt-3 grid gap-1.5">
              {showcaseQuestion.options!.map((option) => {
                const selected = picked && option.id === 'B';
                return (
                  <motion.div key={option.id} data-tap={`opt${option.id}`} animate={{scale: selected && t < 1900 ? 0.98 : 1}}
                    className={cn('flex items-center gap-2.5 rounded-md border px-3 py-2 text-[12px] transition-colors duration-200', selected ? 'border-brand bg-pink-50 text-ink' : 'border-line bg-surface text-text')}>
                    <span className={cn('grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-bold', selected ? 'bg-brand text-white' : 'bg-soft text-muted')}>{option.id}</span>
                    {option.text}
                  </motion.div>
                );
              })}
            </div>
            <p className="mt-2 text-[9.5px] text-muted">{tq('keysMcq')}</p>
          </Panel>
        </div>
        <div className="grid content-start gap-3">
          <Panel className="p-3">
            <p className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-muted"><Clock className="size-3" />{tq('elapsed')}</p>
            <p className="mt-1 font-mono text-[22px] font-bold text-ink">0:{String(seconds).padStart(2, '0')}</p>
          </Panel>
          <Panel className="p-3">
            <p className="text-[9px] font-bold uppercase tracking-wider text-muted">{tq('answeredCount', {answered: picked ? 2 : 1, total: 5})}</p>
            <div className="mt-2 flex gap-1.5">
              {[1, 2, 3, 4, 5].map((n) => (
                <span key={n} className={cn('grid size-7 place-items-center rounded-md text-[11px] font-bold', n === 2 ? 'bg-brand text-white' : n === 1 ? 'bg-pink-100 text-brand' : 'bg-soft text-muted')}>{n}</span>
              ))}
            </div>
            <motion.span data-tap="submit" animate={{scale: t >= 3500 && t < 3700 ? 0.95 : 1}}
              className="mt-3 flex items-center justify-center gap-1.5 rounded-md bg-brand-gradient py-2 text-[12px] font-bold text-white shadow-glow-sm">
              <Send className="size-3.5" />{tq('submit')}
            </motion.span>
          </Panel>
        </div>
      </div>
      <Show when={submitted} className="absolute left-1/2 top-3 -translate-x-1/2">
        <p className="flex items-center gap-2 rounded-md border border-success/30 bg-success-50 px-4 py-2.5 text-[12px] font-semibold text-success shadow-float">
          <CheckCircle2 className="size-4 shrink-0" />{tq('submitted')}
        </p>
      </Show>
    </AppScreen>
  );
}

const BAR = {weak: 'bg-danger', medium: 'bg-warning', strong: 'bg-success', limited_evidence: 'bg-line-strong'} as const;

function ReportScene({t}: {t: number}) {
  const tr = useTranslations('Report');
  const score = Math.round(46 * ease(progress(t, 200, 1300)));
  const open = t >= 3500;
  return (
    <AppScreen active="report">
      <div className="flex gap-4">
        <div className="w-56 rounded-lg bg-brand-gradient px-4 py-3 text-white shadow-glow-sm">
          <p className="text-[9.5px] font-bold uppercase tracking-wider text-white/85">{tr('overall')}</p>
          <p className="text-[34px] font-extrabold leading-none tracking-display">{score}%</p>
          <p className="mt-1 text-[10px] text-white/85">{tr('kindDiagnostic')} · {tr('versionLabel')} 1</p>
        </div>
        <Panel className="flex-1 py-3">
          <p className="text-[9.5px] font-bold uppercase tracking-wider text-muted">{tr('countsLabel')}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {showcaseUnits.map((unit) => <LabelBadge key={unit.label} label={unit.label} />)}
          </div>
          <p className="mt-2 text-[9.5px] leading-snug text-muted">{tr('policyNote').split('. ')[0]}.</p>
        </Panel>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3">
        {showcaseUnits.map((unit, i) => {
          const fill = (unit.mastery ?? 0) * ease(progress(t, 900 + i * 300, 2000 + i * 300));
          const badge = t >= 1900 + i * 300;
          return (
            <Show key={unit.title} when={t >= 500 + i * 250}>
              <div data-tap={`unit${i}`} className={cn('rounded-lg border bg-surface p-3 shadow-card transition-colors', i === 0 && open ? 'border-danger/40' : 'border-line')}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[9.5px] font-semibold text-muted">{tr('priorityRank', {n: i + 1})}</p>
                    <p className="truncate text-[13px] font-bold text-ink">{unit.title}</p>
                  </div>
                  <motion.span initial={false} animate={{scale: badge ? 1 : 0, opacity: badge ? 1 : 0}} transition={{type: 'spring', stiffness: 400, damping: 16}}>
                    <LabelBadge label={unit.label} />
                  </motion.span>
                </div>
                {unit.mastery !== null ? (
                  <>
                    <div className="mt-2 flex justify-between text-[10px]"><span className="font-semibold text-muted">{tr('mastery')}</span><span className="font-bold text-ink">{tr('masteryValue', {value: Math.round(fill)})}</span></div>
                    <div className="mt-1 h-2 overflow-hidden rounded-full bg-soft"><div className={cn('h-full rounded-full', BAR[unit.label])} style={{width: `${fill}%`}} /></div>
                  </>
                ) : <p className="mt-2 text-[10.5px] font-semibold text-muted">{tr('noMastery')}</p>}
                <p className="mt-2 text-[10px] leading-snug text-text">{tr(`reasons.${unit.reason}`, {threshold: 2, levels: ''})}</p>
                {i === 0 && (
                  <motion.div initial={false} animate={{height: open ? 'auto' : 0, opacity: open ? 1 : 0}} className="overflow-hidden">
                    <p className="mt-2 flex items-center gap-1.5 rounded-md bg-cyan-50 px-2 py-1.5 text-[10px] font-semibold text-ink"><Target className="size-3.5 shrink-0 text-[#0284c7]" />{tr('actions.study')}</p>
                  </motion.div>
                )}
              </div>
            </Show>
          );
        })}
      </div>
    </AppScreen>
  );
}

function PlanScene({t}: {t: number}) {
  const tp = useTranslations('Plan');
  const tg = useTranslations('Progress');
  const format = useFormatter();
  const done = t >= 2700;
  const total = showcaseSessions.reduce((sum, s) => sum + s.minutes, 0);
  const minutesDone = done ? showcaseSessions[0].minutes : 0;
  const hours = (m: number) => tp('duration', {hours: Math.floor(m / 60), minutes: m % 60});
  return (
    <AppScreen active="plan">
      <div className="grid grid-cols-[1fr_260px] gap-5">
        <div>
          <Show when={t >= 150}>
            <div className="rounded-md border border-success/30 bg-success-50 px-3 py-2">
              <p className="flex items-center gap-1.5 text-[12px] font-bold text-success"><CalendarCheck className="size-4" />{tp('feasibleTitle')}</p>
              <p className="mt-0.5 text-[10.5px] text-text">{tp('feasibleBody', {need: hours(total), have: hours(240)})}</p>
            </div>
          </Show>
          <Panel className="mt-3 p-3">
            <div className="flex items-center justify-between text-[13px] font-bold text-ink">
              <span className="inline-flex items-center gap-1.5"><CalendarDays className="size-4 text-brand" />{format.dateTime(new Date(`${showcaseSessions[0].day}T00:00:00`), {weekday: 'long', day: 'numeric', month: 'short'})}</span>
              <span className="text-[11px] text-muted">{tp('minutes', {count: total})}</span>
            </div>
            <div className="mt-2 grid gap-1.5">
              {showcaseSessions.map((session, i) => {
                const checked = i === 0 && done;
                const label = session.activity === 'retest' ? tp('retestSession') : session.topic_title;
                return (
                  <Show key={session.id} when={t >= 500 + i * 350}>
                    <div className={cn('flex items-center gap-2.5 rounded-md border px-3 py-2 transition-colors duration-300', checked ? 'border-success/30 bg-success-50' : 'border-line bg-surface')}>
                      <motion.span data-tap={`check${i}`} animate={{scale: i === 0 && t >= 2700 && t < 2900 ? 0.8 : 1}}
                        className={cn('grid size-[18px] shrink-0 place-items-center rounded-[4px] border-2 transition-colors', checked ? 'border-brand bg-brand text-white' : 'border-line-strong bg-surface')}>
                        {checked && <CheckCircle2 className="size-3" />}
                      </motion.span>
                      <div className="min-w-0 flex-1">
                        <p className={cn('truncate text-[12px] font-semibold text-ink', checked && 'line-through decoration-success/60')}>{label}</p>
                        {session.focus.length > 0 && <p className="truncate text-[9.5px] text-muted">{tp('focus', {topics: session.focus.join(', ')})}</p>}
                      </div>
                      <Badge tone={session.activity === 'retest' ? 'brand' : 'info'}>{tp(`activities.${session.activity}`)}</Badge>
                      <span className="w-12 text-right text-[11px] font-semibold text-muted">{tp('minutes', {count: session.minutes})}</span>
                    </div>
                  </Show>
                );
              })}
            </div>
          </Panel>
        </div>
        <Show when={t >= 900}>
          <Panel className="p-3">
            <p className="flex items-center gap-1.5 text-[12px] font-bold text-ink"><CalendarCheck className="size-4 text-brand" />{tg('completionTitle')}</p>
            <p className="text-[9.5px] text-muted">{tg('completionHint')}</p>
            <p className="mt-2.5 text-[11px] text-ink">{tg('completion', {done: done ? 1 : 0, total: showcaseSessions.length, minutesDone, minutesTotal: total})}</p>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-soft"><div className="h-full rounded-full bg-brand-gradient-vivid transition-[width] duration-700" style={{width: `${(minutesDone / total) * 100}%`}} /></div>
            <p className="mt-3 text-[9.5px] leading-snug text-muted">{tp('completionNote')}</p>
          </Panel>
        </Show>
      </div>
    </AppScreen>
  );
}

function ExplainScene({t}: {t: number}) {
  const tx = useTranslations('Explain');
  const question = showcaseExplanation.question;
  const typed = question.slice(0, Math.round(question.length * progress(t, 200, 1500)));
  const thinking = t >= 2000 && t < 2900;
  const answered = t >= 2900;
  const listening = t >= 5600;
  const audio = progress(t, 5600, 8400);
  return (
    <AppScreen active="explain">
      <div className="grid grid-cols-[1fr_290px] gap-5">
        <div>
          <p className="text-[11px] font-bold text-ink">{tx('askLabel')}</p>
          <div className="mt-1.5 flex items-center gap-2">
            <p className="flex-1 rounded-md border border-line-strong bg-surface px-3 py-2 text-[12.5px] text-ink">
              {typed || <span className="text-muted">{tx('placeholder')}</span>}{t < 1900 && <span className="ml-px inline-block h-3.5 w-px animate-pulse bg-brand align-middle" />}
            </p>
            <motion.span data-tap="ask" animate={{scale: t >= 1900 && t < 2100 ? 0.92 : 1}} className="rounded-md bg-brand px-4 py-2 text-[12px] font-bold text-white shadow-glow-sm">{tx('ask')}</motion.span>
          </div>
          {thinking && (
            <p className="mt-3 flex items-center gap-1.5 text-[11px] text-muted">
              {[0, 1, 2].map((i) => <motion.span key={i} className="size-1.5 rounded-full bg-brand" animate={{opacity: [0.2, 1, 0.2]}} transition={{duration: 0.9, repeat: Infinity, delay: i * 0.15}} />)}
              {tx('thinking')}
            </p>
          )}
          <Show when={answered} className="mt-3">
            <Panel>
              <p className="text-[13px] leading-relaxed text-ink">{showcaseExplanation.answer}</p>
              <p className="mt-2 text-[9.5px] text-muted">{tx('groundedNote')}</p>
            </Panel>
          </Show>
        </div>
        <Show when={t >= 3600}>
          <Panel className="p-3">
            <p className="text-[9.5px] font-bold uppercase tracking-wider text-muted">{tx('sources')}</p>
            <div className="mt-1.5 rounded-sm border-l-2 border-brand bg-pink-50 px-2.5 py-2">
              <p className="text-[10px] font-semibold text-plum">{showcaseExplanation.file}</p>
              <p className="mt-0.5 text-[11px] leading-snug text-ink">“{showcaseExplanation.quote}”</p>
            </div>
            <Show when={t >= 4500}>
              <span data-tap="listen" className={cn('mt-3 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[11.5px] font-semibold transition-colors', listening ? 'border-brand bg-pink-50 text-brand' : 'border-line text-ink')}>
                <Volume2 className="size-4" />{tx('listen')}
                {listening && (
                  <span className="ml-1 flex h-3.5 items-center gap-[2px]" aria-hidden>
                    {[0, 1, 2, 3, 4].map((i) => <motion.span key={i} className="w-[2px] rounded-full bg-brand" animate={{height: ['30%', '100%', '45%', '85%', '30%']}} transition={{duration: 0.9, repeat: Infinity, delay: i * 0.12}} />)}
                  </span>
                )}
              </span>
              {listening && (
                <div className="mt-2 flex items-center gap-2 text-[9.5px] text-muted">
                  <span className="font-mono">0:{String(Math.floor(audio * 18)).padStart(2, '0')}</span>
                  <span className="h-1 flex-1 overflow-hidden rounded-full bg-soft"><span className="block h-full rounded-full bg-brand" style={{width: `${audio * 100}%`}} /></span>
                  <span className="font-mono">0:18</span>
                </div>
              )}
            </Show>
          </Panel>
        </Show>
      </div>
    </AppScreen>
  );
}

function OutroScene({onReplay}: {onReplay: () => void}) {
  const t = useTranslations('Home');
  return (
    <div className="relative flex h-full flex-col items-center justify-center overflow-hidden bg-[#14162a] px-10 text-center text-white">
      <span aria-hidden className="absolute -left-24 top-10 size-96 rounded-full bg-brand/35 blur-3xl" />
      <span aria-hidden className="absolute -right-24 bottom-0 size-96 rounded-full bg-cyan/20 blur-3xl" />
      <LogoMark className="relative size-16" />
      <p className="relative mt-5 text-[36px] font-extrabold leading-tight tracking-display">{t('film.outro')}</p>
      <Link href="/login?mode=signup" className="relative mt-6 inline-flex items-center gap-2 rounded-full bg-brand-gradient px-6 py-3 text-[15px] font-bold text-white shadow-glow">
        {t('ctaPrimary')}<ArrowRight className="size-4" />
      </Link>
      <button type="button" onClick={onReplay} className="relative mt-4 inline-flex items-center gap-1.5 text-[13px] font-semibold text-white/75 hover:text-white">
        <RotateCcw className="size-4" />{t('film.replay')}
      </button>
    </div>
  );
}
