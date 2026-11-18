'use client';

import {CalendarDays, ChevronLeft, ChevronRight, ClipboardCheck, Network, Pause, Play, Target, type LucideIcon} from 'lucide-react';
import {AnimatePresence, motion, useReducedMotion} from 'framer-motion';
import {useTranslations} from 'next-intl';
import Image from 'next/image';
import {useCallback, useEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode} from 'react';
import {cn} from '@/lib/utils';
import {DemoFilm} from './demo-film';

/* ---------------- scroll reveal ---------------- */
const wideQuery = '(min-width: 768px)';
function useIsWide() {
  return useSyncExternalStore(
    (notify) => { const mq = window.matchMedia(wideQuery); mq.addEventListener('change', notify); return () => mq.removeEventListener('change', notify); },
    () => window.matchMedia(wideQuery).matches,
    () => false
  );
}

/** Horizontal slide-ins only on wide screens, so nothing starts off-canvas on phones. */
export function Reveal({children, delay = 0, className, x: offset = 0}: {children: ReactNode; delay?: number; className?: string; x?: number}) {
  const x = useIsWide() ? offset : 0;
  return (
    <motion.div
      className={className}
      initial={{opacity: 0, y: x ? 0 : 26, x}}
      whileInView={{opacity: 1, y: 0, x: 0}}
      viewport={{once: true, margin: '-80px'}}
      transition={{duration: 0.7, delay, ease: [0.22, 1, 0.36, 1]}}
    >
      {children}
    </motion.div>
  );
}

/* ---------------- device frames ---------------- */
/** Laptop base seen from the front, as in product shots: hinge, a sliver of deck, the front lip and the opening notch. */
function LaptopBase() {
  const id = useId().replace(/:/g, '');
  return (
    <svg viewBox="0 0 1000 34" aria-hidden className="relative -mx-[6%] block w-[112%] max-w-none drop-shadow-[0_22px_22px_rgba(20,22,42,.16)]">
      <defs>
        <linearGradient id={`${id}t`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#c9cdd7" /><stop offset="1" stopColor="#eef0f4" /></linearGradient>
        <linearGradient id={`${id}f`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#dfe2e9" /><stop offset=".55" stopColor="#c2c7d2" /><stop offset="1" stopColor="#9097a8" /></linearGradient>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#fff" stopOpacity="0" /><stop offset=".5" stopColor="#fff" stopOpacity=".7" /><stop offset="1" stopColor="#fff" stopOpacity="0" /></linearGradient>
      </defs>
      {/* hinge */}
      <rect x="62" y="0" width="876" height="5" rx="1.5" fill="#3a3e52" />
      {/* deck surface, barely visible from the front */}
      <path d="M30 5H970L998 14H2Z" fill={`url(#${id}t)`} />
      {/* front lip */}
      <path d="M2 14H998Q1000 14 1000 17V22Q1000 31 984 32L16 32Q0 31 0 22V17Q0 14 2 14Z" fill={`url(#${id}f)`} />
      <rect x="40" y="14.5" width="920" height="1" fill={`url(#${id}s)`} />
      {/* thumb notch */}
      <path d="M432 14H568Q568 20 558 20H442Q432 20 432 14Z" fill="#a4aab9" />
    </svg>
  );
}

/** Small laptop: dark bezel with a camera dot, the screen, and a silver base with hinge and opening notch. */
export function LaptopFrame({children, className, label}: {children: ReactNode; className?: string; label: string}) {
  return (
    <figure aria-label={label} className={cn('relative mx-auto w-full', className)}>
      <div className="relative rounded-t-[14px] bg-[#14162a] p-[2%] pb-[2%] shadow-float ring-1 ring-black/10 sm:rounded-t-[18px] sm:p-[10px] sm:pb-[14px]">
        <span aria-hidden className="absolute left-1/2 top-[3px] size-1 -translate-x-1/2 rounded-full bg-white/25 sm:top-1 sm:size-1.5" />
        <div className="relative overflow-hidden rounded-[4px] bg-[#14162a] sm:rounded-[6px]">{children}</div>
      </div>
      <LaptopBase />
    </figure>
  );
}

export function BrowserFrame({children, className, url = 'gapfinder.app'}: {children: ReactNode; className?: string; url?: string}) {
  return (
    <div className={cn('overflow-hidden rounded-xl border border-line bg-surface shadow-float', className)}>
      <div className="flex items-center gap-2 border-b border-line bg-canvas px-4 py-3" aria-hidden>
        <span className="size-2.5 rounded-full bg-[#ff5f57]" /><span className="size-2.5 rounded-full bg-[#febc2e]" /><span className="size-2.5 rounded-full bg-[#28c840]" />
        <span className="ml-3 truncate rounded-full bg-soft px-3 py-0.5 text-[11px] text-muted">{url}</span>
      </div>
      <div className="p-4 sm:p-5">{children}</div>
    </div>
  );
}

/* ---------------- hero: laptop film + feature cards ---------------- */
function FeatureCard({icon: Icon, title, body, tone, delay, step}: {icon: LucideIcon; title: string; body: string; tone: string; delay: number; step: number}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : {opacity: 0, y: 18}}
      animate={{opacity: 1, y: 0}}
      transition={{delay, duration: 0.6, ease: [0.22, 1, 0.36, 1]}}
      whileHover={{y: -3}}
      className="flex h-full items-start gap-3 rounded-lg border border-line bg-surface p-4 shadow-card transition-shadow hover:shadow-float"
    >
      <span className={cn('grid size-10 shrink-0 place-items-center rounded-full', tone)}><Icon className="size-5" /></span>
      <span>
        <span className="block text-[11px] font-bold uppercase tracking-[0.14em] text-muted">0{step}</span>
        <h3 className="text-[15px] font-bold leading-snug">{title}</h3>
        <p className="mt-0.5 text-[13px] leading-snug text-muted">{body}</p>
      </span>
    </motion.div>
  );
}

export function HeroShowcase({intro}: {intro: ReactNode}) {
  const t = useTranslations('Home');
  const reduce = useReducedMotion();
  // Same order as the film: material → diagnose → gaps → plan and explain.
  const cards = [
    {icon: Network, title: t('cardUploadTitle'), body: t('cardUploadBody'), tone: 'bg-pink-100 text-brand'},
    {icon: ClipboardCheck, title: t('cardMapTitle'), body: t('cardMapBody'), tone: 'bg-cyan-50 text-[#0284c7]'},
    {icon: Target, title: t('cardImportanceTitle'), body: t('cardImportanceBody'), tone: 'bg-warning-50 text-warning'},
    {icon: CalendarDays, title: t('cardLanguageTitle'), body: t('cardLanguageBody'), tone: 'bg-[#f3e8f0] text-plum'}
  ];
  return (
    <div className="relative mx-auto max-w-[77rem]">
      <div className="grid items-center gap-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-6">
        {intro}
        <motion.div
          className="relative mx-auto w-full max-w-3xl lg:max-w-none lg:pr-[5%] [perspective:1800px]"
          initial={reduce ? false : {opacity: 0, x: 40}}
          animate={{opacity: 1, x: 0}}
          transition={{duration: 0.8, delay: 0.15, ease: [0.22, 1, 0.36, 1]}}
        >
          <span aria-hidden className="absolute inset-x-[8%] -bottom-4 top-[15%] -z-10 rounded-full bg-brand/20 blur-3xl" />
          {/* Tilted only on wide screens; flat on phones so the film stays readable. */}
          <div className="transition-transform duration-500 ease-out lg:[transform:rotateY(-13deg)_rotateX(4deg)_rotateZ(1deg)] lg:hover:[transform:rotateY(-6deg)_rotateX(2deg)]">
            <LaptopFrame label={t('phoneCaption')}><DemoFilm /></LaptopFrame>
          </div>
        </motion.div>
      </div>
      <ul className="mt-14 grid gap-3 sm:grid-cols-2 lg:mt-24 lg:grid-cols-4">
        {cards.map((card, index) => <li key={card.title}><FeatureCard {...card} step={index + 1} delay={0.5 + index * 0.12} /></li>)}
      </ul>
    </div>
  );
}

/* ---------------- timeline: wavy horizontal map (lg+), vertical list below ---------------- */
type TimelineStep = {title: string; body: string; icon: LucideIcon};

export function Timeline({steps}: {steps: TimelineStep[]}) {
  return (
    <>
      <WaveMap steps={steps} />
      <VerticalTimeline steps={steps} />
    </>
  );
}

/**
 * All steps on one screen: nodes sit on a wave that alternates crest/trough,
 * cards for crest nodes sit above the wave and cards for trough nodes below it.
 * Node i is centred on half-column 2(i+1) of a 2(n+1)-column grid, and each card spans
 * the 4 half-columns around its node, so same-side neighbours touch but never overlap.
 */
function WaveMap({steps}: {steps: TimelineStep[]}) {
  const reduce = useReducedMotion();
  const n = steps.length;
  const unit = 100; // SVG units between nodes
  const width = unit * (n + 1);
  const crest = 22;
  const trough = 98;
  const points = steps.map((_, i) => ({x: unit * (i + 1), y: i % 2 === 0 ? crest : trough}));
  const all = [{x: 0, y: 60}, ...points, {x: width, y: 60}];
  const d = all.reduce((path, p, i) => {
    if (i === 0) return `M${p.x},${p.y}`;
    const prev = all[i - 1];
    const mid = (p.x - prev.x) / 2;
    return `${path} C${prev.x + mid},${prev.y} ${p.x - mid},${p.y} ${p.x},${p.y}`;
  }, '');
  const columns = {gridTemplateColumns: `repeat(${2 * (n + 1)}, minmax(0, 1fr))`};

  const card = (step: TimelineStep, i: number, above: boolean) => (
    <li
      key={step.title}
      className={cn('row-start-1 flex px-1.5', above ? 'items-end' : 'items-start')}
      style={{gridColumn: `${2 * i + 1} / span 4`}}
    >
      <Reveal className="w-full" delay={reduce ? 0 : i * 0.06}>
        <div className="rounded-lg border border-line bg-surface p-4 shadow-card transition-shadow hover:shadow-float">
          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-brand">{String(i + 1).padStart(2, '0')}</p>
          <h3 className="mt-1 text-[15px] leading-snug">{step.title}</h3>
          <p className="mt-1 text-[13px] leading-snug text-muted">{step.body}</p>
        </div>
      </Reveal>
    </li>
  );

  return (
    <div className="mx-auto mt-12 hidden max-w-7xl lg:block">
      <ol className="grid" style={columns}>
        {steps.map((step, i) => (i % 2 === 0 ? card(step, i, true) : null))}
      </ol>

      <div className="relative my-3 h-[120px]" aria-hidden>
        <svg viewBox={`0 0 ${width} 120`} preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible">
          <defs>
            <linearGradient id="wave-map-stroke" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="var(--color-brand)" />
              <stop offset="55%" stopColor="var(--color-plum)" />
              <stop offset="100%" stopColor="var(--color-amber)" />
            </linearGradient>
          </defs>
          <path d={d} fill="none" stroke="var(--color-line)" strokeWidth="6" strokeLinecap="round" opacity="0.6" />
          <motion.path
            d={d}
            fill="none"
            stroke="url(#wave-map-stroke)"
            strokeWidth="3"
            strokeLinecap="round"
            initial={reduce ? false : {pathLength: 0}}
            whileInView={{pathLength: 1}}
            viewport={{once: true, margin: '-80px'}}
            transition={{duration: 1.8, ease: 'easeInOut'}}
          />
        </svg>
        {steps.map((step, i) => (
          <motion.span
            key={step.title}
            className="absolute grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border-4 border-surface bg-brand-gradient text-white shadow-glow"
            style={{left: `${(points[i].x / width) * 100}%`, top: points[i].y}}
            initial={reduce ? false : {scale: 0.6, opacity: 0}}
            whileInView={{scale: 1, opacity: 1}}
            viewport={{once: true, margin: '-80px'}}
            transition={{duration: 0.45, delay: reduce ? 0 : 0.2 + i * 0.15}}
          >
            <step.icon className="size-[18px]" />
          </motion.span>
        ))}
      </div>

      <ol className="grid" style={columns}>
        {steps.map((step, i) => (i % 2 === 1 ? card(step, i, false) : null))}
      </ol>
    </div>
  );
}

function VerticalTimeline({steps}: {steps: TimelineStep[]}) {
  return (
    <ol className="relative mx-auto mt-14 max-w-4xl lg:hidden">
      <span aria-hidden className="absolute left-6 top-2 h-[calc(100%-1rem)] w-0.5 bg-gradient-to-b from-brand via-plum to-amber md:left-1/2 md:-translate-x-1/2" />
      {steps.map((step, index) => {
        const right = index % 2 === 1;
        return (
          <li key={step.title} className="relative grid grid-cols-[3rem_1fr] gap-4 pb-10 last:pb-0 md:grid-cols-[1fr_3.5rem_1fr] md:gap-8">
            <Reveal className={cn('col-start-2 md:col-start-1 md:row-start-1', right ? 'md:col-start-3' : 'md:text-right')} x={right ? 24 : -24}>
              <div className="rounded-lg border border-line bg-surface p-5 shadow-card">
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-brand">0{index + 1}</p>
                <h3 className="mt-1 text-lg">{step.title}</h3>
                <p className="mt-1.5 text-[15px] text-muted">{step.body}</p>
              </div>
            </Reveal>
            <motion.span
              className="col-start-1 row-start-1 grid size-12 place-items-center rounded-full border-4 border-canvas bg-brand-gradient text-white shadow-glow md:col-start-2"
              initial={{scale: 0.6, opacity: 0}}
              whileInView={{scale: 1, opacity: 1}}
              viewport={{once: true, margin: '-80px'}}
              transition={{duration: 0.5}}
            >
              <step.icon className="size-5" aria-hidden />
            </motion.span>
          </li>
        );
      })}
    </ol>
  );
}

/* ---------------- product tour slider (real screenshots) ---------------- */
export type TourSlide = {src: string; width: number; height: number; title: string; body: string; icon: LucideIcon};

const TOUR_INTERVAL = 6000;

/**
 * Product tour: a numbered step rail on the left, one large screen on the right.
 * The active step opens to show its description and fills a progress line while the tour plays.
 * The screen's width is capped by the viewport height, so rail and screen always fit one screen.
 */
export function ProductTour({slides}: {slides: TourSlide[]}) {
  const t = useTranslations('Home');
  const reduce = useReducedMotion();
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(!reduce);
  const touchStart = useRef<number | null>(null);
  const go = useCallback((next: number) => setIndex((next + slides.length) % slides.length), [slides.length]);

  useEffect(() => {
    if (!playing || reduce || slides.length < 2) return;
    const timer = window.setInterval(() => setIndex((i) => (i + 1) % slides.length), TOUR_INTERVAL);
    return () => window.clearInterval(timer);
  }, [playing, reduce, slides.length]);

  const slide = slides[index];
  const manual = (next: number) => { setPlaying(false); go(next); };
  const arrowClass = 'grid size-9 place-items-center rounded-full border border-line bg-surface text-ink transition-colors hover:border-brand hover:text-brand';
  return (
    <div
      className="mx-auto mt-6 grid max-w-7xl grid-cols-1 gap-5 lg:grid-cols-[19rem_minmax(0,1fr)] lg:items-center lg:gap-8"
      role="region"
      aria-roledescription="carousel"
      aria-label={t('tourTitle')}
      onKeyDown={(event) => {
        if (event.key === 'ArrowRight') manual(index + 1);
        if (event.key === 'ArrowLeft') manual(index - 1);
      }}
    >
      {/* Screen */}
      <div className="lg:order-2">
        <div
          className="mx-auto w-full"
          style={{maxWidth: `calc((100svh - 15rem) * ${slide.width / (slide.height + 44)})`}}
          aria-live={playing ? 'off' : 'polite'}
          onTouchStart={(event) => { touchStart.current = event.touches[0].clientX; }}
          onTouchEnd={(event) => {
            if (touchStart.current === null) return;
            const delta = event.changedTouches[0].clientX - touchStart.current;
            if (Math.abs(delta) > 40) manual(index + (delta < 0 ? 1 : -1));
            touchStart.current = null;
          }}
        >
          <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-float">
            <div className="flex items-center gap-1.5 border-b border-line bg-soft/60 px-4 py-3" aria-hidden>
              <span className="size-2.5 rounded-full bg-[#ff5f57]" /><span className="size-2.5 rounded-full bg-[#febc2e]" /><span className="size-2.5 rounded-full bg-[#28c840]" />
              <span className="ml-3 truncate rounded-full bg-surface px-3 py-0.5 text-[11px] text-muted">gapfinder.app · {slide.title}</span>
            </div>
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={slide.src} initial={{opacity: 0, x: 48}} animate={{opacity: 1, x: 0}} exit={{opacity: 0, x: -48}} transition={{duration: 0.4, ease: [0.22, 1, 0.36, 1]}}>
                <Image src={slide.src} alt={`${slide.title} — ${slide.body}`} width={slide.width} height={slide.height} className="h-auto w-full" sizes="(min-width: 1280px) 940px, 100vw" priority={index === 0} />
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* Step rail */}
      <div className="lg:order-1">
        <ol className="grid grid-cols-1 gap-1 sm:grid-cols-2 lg:grid-cols-1">
          {slides.map((item, i) => {
            const active = i === index;
            return (
              <li key={item.src}>
                <button
                  type="button"
                  aria-current={active}
                  onClick={() => manual(i)}
                  className={cn('relative block w-full overflow-hidden rounded-lg px-3 py-2.5 text-left transition-colors duration-300', active ? 'bg-pink-50' : 'hover:bg-soft/70')}
                >
                  <span className="flex items-center gap-3">
                    <span className={cn('grid size-8 shrink-0 place-items-center rounded-full text-[13px] font-bold transition-colors duration-300', active ? 'bg-brand text-white' : 'bg-soft text-muted')}>
                      {active ? <item.icon className="size-4" aria-hidden /> : i + 1}
                    </span>
                    <span className={cn('min-w-0 break-words text-[15px] font-semibold leading-snug transition-colors duration-300', active ? 'text-brand' : 'text-ink')}>{item.title}</span>
                  </span>
                  <AnimatePresence initial={false}>
                    {active && (
                      <motion.span
                        key="body"
                        initial={{height: 0, opacity: 0}}
                        animate={{height: 'auto', opacity: 1}}
                        exit={{height: 0, opacity: 0}}
                        transition={{duration: 0.3}}
                        className="block overflow-hidden"
                      >
                        <span className="block pb-1.5 pl-11 pt-1.5 text-[13px] leading-snug text-muted">{item.body}</span>
                      </motion.span>
                    )}
                  </AnimatePresence>
                  {active && (
                    <motion.span
                      key={`${index}-${playing}`}
                      aria-hidden
                      className="absolute inset-x-0 bottom-0 h-[3px] origin-left bg-brand"
                      initial={{scaleX: playing ? 0 : 1}}
                      animate={{scaleX: 1}}
                      transition={playing ? {duration: TOUR_INTERVAL / 1000, ease: 'linear'} : {duration: 0}}
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ol>
        <div className="mt-3 flex items-center gap-2 pl-3">
          <button type="button" aria-label={t('tourPrev')} onClick={() => manual(index - 1)} className={arrowClass}><ChevronLeft className="size-4" /></button>
          <button type="button" aria-label={t('tourNext')} onClick={() => manual(index + 1)} className={arrowClass}><ChevronRight className="size-4" /></button>
          {!reduce && (
            <button type="button" aria-label={playing ? t('tourPause') : t('tourPlay')} onClick={() => setPlaying(!playing)} className="grid size-9 place-items-center rounded-full text-muted transition-colors hover:text-brand">
              {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
            </button>
          )}
          <span className="ml-1 text-xs font-semibold tabular-nums text-muted" aria-hidden>{index + 1} / {slides.length}</span>
        </div>
      </div>
    </div>
  );
}
