'use client';

import {ArrowRight, BookOpen, CalendarDays, CheckCircle2, ClipboardCheck, Eraser, FileStack, FolderLock, FolderPlus, Image as ImageIcon, LineChart, Lock, MessageCircleQuestion, Network, Quote, RotateCcw, ScanSearch, ShieldCheck, Target, UploadCloud, Volume2, type LucideIcon} from 'lucide-react';
import {useTranslations} from 'next-intl';
import type {ReactNode} from 'react';
import {PipelineSteps, StateBadge} from '@/components/app/shared';
import {ImportanceMeter, TopicTree} from '@/components/app/topic-tree';
import {Button} from '@/components/ui/button';
import {Accordion, AccordionItem, Badge} from '@/components/ui/primitives';
import {Link} from '@/i18n/navigation';
import {LabelBadge, MasteryBar} from '@/components/app/gap-report';
import {SessionLine} from '@/components/app/plan-panel';
import {AnswerInput} from '@/components/app/quiz-attempt';
import {showcaseCitation, showcaseExplanation, showcaseFiles, showcaseQuestion, showcaseSessions, showcaseTopics, showcaseUnits} from '@/lib/showcase';
import {cn} from '@/lib/utils';
import {SectionLink} from './section-link';
import {BrowserFrame, HeroShowcase, ProductTour, Reveal, Timeline, type TourSlide} from './showcase';

function SectionHeading({eyebrow, title, body, light, oneLine}: {eyebrow: string; title: string; body?: string; light?: boolean; oneLine?: boolean}) {
  return (
    <Reveal className={cn('mx-auto text-center', oneLine ? 'max-w-6xl' : 'max-w-2xl')}>
      <p className={cn('text-sm font-bold uppercase tracking-[0.18em]', light ? 'text-amber' : 'text-brand')}>{eyebrow}</p>
      <h2 className={cn('mt-3 text-3xl sm:text-[2.6rem]', oneLine && 'lg:whitespace-nowrap', light && 'text-white')}>{title}</h2>
      {body && <p className={cn('mx-auto mt-4 max-w-2xl text-lg', light ? 'text-white/75' : 'text-muted')}>{body}</p>}
    </Reveal>
  );
}

function FeatureRow({title, body, points, preview, reverse, icon: Icon}: {title: string; body: string; points: string[]; preview: ReactNode; reverse?: boolean; icon: LucideIcon}) {
  return (
    <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-2 lg:gap-16">
      <Reveal x={reverse ? 30 : -30} className={cn(reverse && 'lg:order-2')}>
        <div className="relative">
          <div aria-hidden className={cn('absolute -inset-4 -z-10 rounded-[32px] sm:-inset-8', reverse ? 'bg-cyan-50' : 'bg-pink-100')} />
          {preview}
        </div>
      </Reveal>
      <Reveal x={reverse ? -30 : 30}>
        <span className="grid size-12 place-items-center rounded-full bg-brand-gradient text-white shadow-glow-sm"><Icon className="size-5" /></span>
        <h3 className="mt-5 text-2xl sm:text-3xl">{title}</h3>
        <p className="mt-4 text-[17px]">{body}</p>
        <ul className="mt-6 grid gap-3">
          {points.map((point) => (
            <li key={point} className="flex items-start gap-3 font-medium text-ink"><CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" />{point}</li>
          ))}
        </ul>
      </Reveal>
    </div>
  );
}

function CitationPreview() {
  const t = useTranslations('Topics');
  const tc = useTranslations('Common');
  const tl = useTranslations('Locale');
  return (
    <BrowserFrame>
      <p className="text-sm font-bold text-ink">{t('evidenceTitle', {title: 'Mitosis and meiosis'})}</p>
      <div className="mt-4 rounded-md border border-line p-4">
        <p className="flex flex-wrap items-center gap-2 text-xs font-semibold text-muted">
          <Badge tone="brand">{showcaseCitation.file}</Badge>
          <span>{tc('page', {page: showcaseCitation.page})}</span>
          <span>· {showcaseCitation.heading}</span>
        </p>
        <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-plum">{t('originalQuote', {language: tl('en')})}</p>
        <blockquote className="mt-1 border-l-[3px] border-brand bg-pink-50 px-3 py-2 text-[15px] text-ink">“{showcaseCitation.quote}”</blockquote>
        <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">{t('translation', {language: tl('hi-IN')})}</p>
        <p lang="hi" className="mt-1 border-l-[3px] border-line-strong px-3 py-1 text-sm">{showcaseCitation.translation}</p>
      </div>
    </BrowserFrame>
  );
}

function ImportancePreview() {
  const t = useTranslations('Topics');
  return (
    <BrowserFrame>
      <ul className="grid gap-3">
        {showcaseTopics.filter((topic) => topic.importance_source !== 'default').slice(0, 4).map((topic) => (
          <li key={topic.id} className="flex items-center justify-between gap-3 rounded-md border border-line px-4 py-3">
            <div className="min-w-0">
              <p className="truncate font-semibold text-ink">{topic.title}</p>
              <p className="text-xs text-muted">{t('pastPaperCount', {count: topic.past_paper_question_count})}</p>
            </div>
            <ImportanceMeter topic={topic} />
          </li>
        ))}
      </ul>
    </BrowserFrame>
  );
}

function ProcessingPreview() {
  const t = useTranslations('Materials');
  return (
    <BrowserFrame>
      <ul className="grid gap-3">
        {showcaseFiles.map((file) => (
          <li key={file.name} className="flex flex-wrap items-center gap-3 rounded-md border border-line p-3.5">
            <span className="grid size-9 place-items-center rounded-sm bg-pink-100 text-brand"><FileStack className="size-4" /></span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-ink">{file.name}</p>
              <p className="text-xs text-muted">{t(`roles.${file.role}`)}</p>
            </div>
            <PipelineSteps state={file.state} />
            <StateBadge state={file.state} />
          </li>
        ))}
      </ul>
    </BrowserFrame>
  );
}

function DiagnosePreview() {
  const tq = useTranslations('Quiz');
  return (
    <BrowserFrame>
      <p className="flex flex-wrap items-center gap-2 text-xs font-semibold text-muted">
        <span>{tq('questionN', {n: 2})}</span><span>· {showcaseQuestion.topic_title}</span>
        <Badge tone="success"><CheckCircle2 className="size-3.5" />{tq('verdicts.correct')}</Badge>
      </p>
      <p className="mt-2 font-semibold text-ink">{showcaseQuestion.prompt}</p>
      <div className="mt-3"><AnswerInput question={showcaseQuestion} value="B" onChange={() => undefined} /></div>
      <div className="mt-3 rounded-sm bg-pink-50 px-3 py-2 text-sm">
        <p className="text-xs font-semibold text-plum">{showcaseCitation.file}</p>
        <p className="mt-1 text-ink">“{showcaseCitation.quote}”</p>
      </div>
    </BrowserFrame>
  );
}

function ReportPlanPreview() {
  const tr = useTranslations('Report');
  return (
    <BrowserFrame>
      <ul className="grid gap-3">
        {showcaseUnits.slice(0, 2).map((unit) => (
          <li key={unit.title} className="rounded-md border border-line p-3.5">
            <div className="flex items-center justify-between gap-2"><p className="font-bold text-ink">{unit.title}</p><LabelBadge label={unit.label} /></div>
            <div className="mt-2"><MasteryBar label={unit.label} mastery={unit.mastery} /></div>
            <p className="mt-2 text-xs text-text">{tr(`reasons.${unit.reason}`, {threshold: 2, levels: ''})}</p>
          </li>
        ))}
      </ul>
      <ul className="mt-3 grid gap-2">
        {showcaseSessions.slice(0, 2).map((session) => (
          <SessionLine key={session.id} session={session} done={Boolean(session.completed_at)}
            control={<input type="checkbox" className="size-5 accent-[#ce007b]" checked={Boolean(session.completed_at)} readOnly tabIndex={-1} aria-hidden />} />
        ))}
      </ul>
    </BrowserFrame>
  );
}

function ExplainPreview() {
  const tx = useTranslations('Explain');
  return (
    <BrowserFrame>
      <p className="text-sm font-semibold text-muted">{showcaseExplanation.question}</p>
      <p className="mt-2 text-[15px] leading-relaxed text-ink">{showcaseExplanation.answer}</p>
      <p className="mt-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted"><BookOpen className="size-4" />{tx('sources')}</p>
      <div className="mt-1 rounded-sm bg-pink-50 px-3 py-2 text-sm">
        <p className="text-xs font-semibold text-plum">{showcaseExplanation.file}</p>
        <p className="mt-1 text-ink">“{showcaseExplanation.quote}”</p>
      </div>
      <div className="mt-3 flex flex-wrap gap-2" aria-hidden>
        <span className="inline-flex items-center gap-2 rounded-sm border border-line bg-surface px-3 py-1.5 text-sm font-semibold text-ink"><Volume2 className="size-4" />{tx('listen')}</span>
        <span className="inline-flex items-center gap-2 rounded-sm border border-line bg-surface px-3 py-1.5 text-sm font-semibold text-ink"><ImageIcon className="size-4" />{tx('illustrate')}</span>
      </div>
      <p className="mt-2 text-xs text-muted">{tx('aiLabel')}</p>
    </BrowserFrame>
  );
}

export function Landing({tour}: {tour: {src: string; width: number; height: number; key: string}[]}) {
  const t = useTranslations('Home');
  const tourMeta: Record<string, {title: string; body: string; icon: LucideIcon}> = {
    dashboard: {title: t('tour1Title'), body: t('tour1Body'), icon: FolderPlus},
    materials: {title: t('tour2Title'), body: t('tour2Body'), icon: UploadCloud},
    topics: {title: t('tour3Title'), body: t('tour3Body'), icon: Network},
    evidence: {title: t('tour4Title'), body: t('tour4Body'), icon: Quote},
    quiz: {title: t('tour5Title'), body: t('tour5Body'), icon: ClipboardCheck},
    review: {title: t('tour6Title'), body: t('tour6Body'), icon: CheckCircle2},
    report: {title: t('tour7Title'), body: t('tour7Body'), icon: Target},
    plan: {title: t('tour8Title'), body: t('tour8Body'), icon: CalendarDays},
    progress: {title: t('tour9Title'), body: t('tour9Body'), icon: LineChart},
    explain: {title: t('tour10Title'), body: t('tour10Body'), icon: MessageCircleQuestion}
  };
  const order = Object.keys(tourMeta); // narrative order, independent of capture order
  const slides: TourSlide[] = tour
    .filter((item) => tourMeta[item.key])
    .sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key))
    .map((item) => ({...item, ...tourMeta[item.key]}));
  return (
    <main id="main">
      {/* Hero */}
      <section className="relative overflow-hidden px-4 pb-10 pt-10 sm:px-6 sm:pt-14 lg:pb-14 lg:pt-20">
        <div aria-hidden className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,#ffe3f2,transparent)]" />
        <HeroShowcase
          intro={
            <Reveal className="text-center lg:text-left">
              <h1 className="text-[2.6rem] leading-[1.05] sm:text-5xl lg:text-[3.3rem] xl:text-[3.9rem]">
                {t.rich('title', {gradient: (chunks) => <span className="text-brand-gradient">{chunks}</span>})}
              </h1>
              <p className="mx-auto mt-4 max-w-2xl text-lg sm:text-xl lg:mx-0 lg:mt-6 lg:max-w-xl lg:text-[1.3rem] lg:leading-relaxed">{t('subtitle')}</p>
              <div className="mt-6 flex flex-wrap justify-center gap-3 lg:mt-9 lg:justify-start">
                <Button asChild size="lg" variant="gradient" className="lg:h-14 lg:px-7 lg:text-base"><Link href="/login?mode=signup">{t('ctaPrimary')}<ArrowRight /></Link></Button>
                <Button asChild size="lg" variant="secondary" className="lg:h-14 lg:px-7 lg:text-base"><SectionLink href="/#how">{t('ctaSecondary')}</SectionLink></Button>
              </div>
            </Reveal>
          }
        />
      </section>

      {/* How it works — wavy horizontal map (vertical on small screens) */}
      <section id="how" className="scroll-mt-20 bg-surface px-4 py-20 sm:px-6 sm:py-28">
        <SectionHeading eyebrow={t('howEyebrow')} title={t('howTitle')} body={t('howSubtitle')} oneLine />
        <Timeline
          steps={[
            {title: t('step1Title'), body: t('step1Body'), icon: FolderPlus},
            {title: t('step2Title'), body: t('step2Body'), icon: UploadCloud},
            {title: t('step3Title'), body: t('step3Body'), icon: ScanSearch},
            {title: t('step4Title'), body: t('step4Body'), icon: Network},
            {title: t('step5Title'), body: t('step5Body'), icon: CheckCircle2},
            {title: t('step6Title'), body: t('step6Body'), icon: ClipboardCheck},
            {title: t('step7Title'), body: t('step7Body'), icon: Target},
            {title: t('step8Title'), body: t('step8Body'), icon: CalendarDays},
            {title: t('step9Title'), body: t('step9Body'), icon: RotateCcw},
            {title: t('step10Title'), body: t('step10Body'), icon: MessageCircleQuestion}
          ]}
        />
      </section>

      {/* Alternating features */}
      <section id="features" className="scroll-mt-20 overflow-x-clip px-4 py-20 sm:px-6 sm:py-28">
        <SectionHeading eyebrow={t('featuresEyebrow')} title={t('featuresTitle')} body={t('featuresBody')} />
        <div className="mx-auto mt-16 grid max-w-6xl gap-24">
          <FeatureRow icon={Quote} title={t('feature1Title')} body={t('feature1Body')} points={[t('feature1Point1'), t('feature1Point2'), t('feature1Point3')]} preview={<CitationPreview />} />
          <FeatureRow reverse icon={Network} title={t('feature2Title')} body={t('feature2Body')} points={[t('feature2Point1'), t('feature2Point2'), t('feature2Point3')]} preview={<ImportancePreview />} />
          <FeatureRow icon={ScanSearch} title={t('feature3Title')} body={t('feature3Body')} points={[t('feature3Point1'), t('feature3Point2'), t('feature3Point3')]} preview={<ProcessingPreview />} />
          <FeatureRow reverse icon={ClipboardCheck} title={t('feature4Title')} body={t('feature4Body')} points={[t('feature4Point1'), t('feature4Point2'), t('feature4Point3')]} preview={<DiagnosePreview />} />
          <FeatureRow icon={Target} title={t('feature5Title')} body={t('feature5Body')} points={[t('feature5Point1'), t('feature5Point2'), t('feature5Point3')]} preview={<ReportPlanPreview />} />
          <FeatureRow reverse icon={MessageCircleQuestion} title={t('feature6Title')} body={t('feature6Body')} points={[t('feature6Point1'), t('feature6Point2'), t('feature6Point3')]} preview={<ExplainPreview />} />
        </div>
      </section>

      {/* Dark showcase */}
      <section className="relative overflow-hidden bg-dark-gradient px-4 py-20 text-white sm:px-6 sm:py-28">
        <div aria-hidden className="pointer-events-none absolute -right-40 top-10 size-[420px] rounded-full bg-brand/25 blur-3xl" />
        <div className="relative mx-auto grid max-w-6xl grid-cols-1 items-center gap-14 lg:grid-cols-2">
          <div>
            <Reveal>
              <p className="text-sm font-bold uppercase tracking-[0.18em] text-amber">{t('darkEyebrow')}</p>
              <h2 className="mt-3 text-3xl text-white sm:text-[2.6rem]">{t('darkTitle')}</h2>
              <p className="mt-4 text-lg text-white/75">{t('darkBody')}</p>
            </Reveal>
            <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-2">
              {([
                [FolderLock, t('dark1Title'), t('dark1Body')],
                [Lock, t('dark2Title'), t('dark2Body')],
                [Eraser, t('dark3Title'), t('dark3Body')],
                [ShieldCheck, t('dark4Title'), t('dark4Body')]
              ] as const).map(([Icon, title, body], index) => (
                <Reveal key={title} delay={index * 0.08}>
                  <span className="grid size-12 place-items-center rounded-full bg-white/10 text-amber ring-1 ring-white/15"><Icon className="size-5" /></span>
                  <h3 className="mt-4 text-lg text-white">{title}</h3>
                  <p className="mt-1 text-sm text-white/70">{body}</p>
                </Reveal>
              ))}
            </div>
          </div>
          <Reveal x={40}>
            <div className="rounded-xl bg-white/5 p-3 ring-1 ring-white/10 sm:p-5">
              <div className="rounded-lg bg-canvas p-4 sm:p-5">
                <TopicTree topics={showcaseTopics.slice(0, 4)} />
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* Product tour with real screenshots (rendered only when captured screenshots exist) */}
      {slides.length > 0 && (
        <section className="px-4 py-8 sm:px-6 sm:py-8">
          <div className="mx-auto max-w-7xl">
            <SectionHeading eyebrow={t('tourEyebrow')} title={t('tourTitle')} />
            <ProductTour slides={slides} />
          </div>
        </section>
      )}

      {/* FAQ */}
      <section id="faq" className="scroll-mt-20 bg-surface px-4 py-20 sm:px-6 sm:py-28">
        <div className="mx-auto grid max-w-6xl grid-cols-1 gap-12 lg:grid-cols-[2fr_3fr]">
          <div className="lg:sticky lg:top-28 lg:h-fit">
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-brand">{t('faqEyebrow')}</p>
            <h2 className="mt-3 text-3xl sm:text-[2.6rem]">{t('faqTitle')}</h2>
          </div>
          <Accordion type="single" collapsible defaultValue="q1" className="grid gap-3">
            {(['1', '2', '3', '4', '5', '7'] as const).map((n) => (
              <AccordionItem key={n} value={`q${n}`} question={t(`faq${n}Q`)}>{t(`faq${n}A`)}</AccordionItem>
            ))}
          </Accordion>
        </div>
      </section>

      {/* CTA band */}
      <section className="px-4 py-20 sm:px-6">
        <Reveal className="mx-auto max-w-5xl">
          <div className="relative overflow-hidden rounded-xl bg-brand-gradient px-6 py-14 text-center text-white shadow-glow sm:px-12">
            <div aria-hidden className="pointer-events-none absolute -left-20 -top-20 size-64 rounded-full bg-white/15 blur-2xl" />
            <h2 className="relative text-3xl text-white sm:text-4xl">{t('ctaTitle')}</h2>
            <p className="relative mx-auto mt-3 max-w-xl text-white/85">{t('ctaBody')}</p>
            <Button asChild size="lg" variant="dark" className="relative mt-8"><Link href="/login?mode=signup">{t('ctaButton')}<ArrowRight /></Link></Button>
          </div>
        </Reveal>
      </section>
    </main>
  );
}
