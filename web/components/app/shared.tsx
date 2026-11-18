'use client';

import {AlertCircle, Check, Loader2} from 'lucide-react';
import {useTranslations} from 'next-intl';
import {usePathname, useRouter} from '@/i18n/navigation';
import {htmlLang, locales, type AppLocale} from '@/i18n/config';
import {useLocale} from 'next-intl';
import {ApiError, type DocumentState} from '@/lib/api';
import {Badge, Select} from '@/components/ui/primitives';
import {cn} from '@/lib/utils';

export const PIPELINE: DocumentState[] = ['scanning', 'extracting', 'chunking', 'embedding', 'mapping', 'ready'];

/** Localised message for any API/network error. */
export function useErrorText() {
  const t = useTranslations('Errors');
  return (error: unknown) => {
    if (error instanceof ApiError) return t.has(error.code) ? t(error.code as 'INTERNAL_ERROR') : error.message;
    return t('network');
  };
}

export function StateBadge({state}: {state: DocumentState}) {
  const t = useTranslations('States');
  if (state === 'ready') return <Badge tone="success"><Check className="size-3.5" />{t('ready')}</Badge>;
  if (state === 'failed') return <Badge tone="danger"><AlertCircle className="size-3.5" />{t('failed')}</Badge>;
  return <Badge tone="brand"><Loader2 className="size-3.5 animate-spin" />{t(state)}</Badge>;
}

/** Five-dot progress through the processing pipeline. */
export function PipelineSteps({state}: {state: DocumentState}) {
  const t = useTranslations('States');
  const index = state === 'ready' ? PIPELINE.length : PIPELINE.indexOf(state);
  if (state === 'failed' || state === 'uploaded') return null;
  return (
    <ol className="flex items-center gap-1.5" aria-label={t(state)}>
      {PIPELINE.slice(0, -1).map((step, i) => (
        <li key={step} title={t(step)} className={cn('h-1.5 w-6 rounded-full transition-colors duration-500', i < index ? 'bg-brand' : i === index ? 'bg-brand/40 animate-pulse' : 'bg-soft')} />
      ))}
    </ol>
  );
}

export function LocaleSelect({onChange, className}: {onChange?: (locale: AppLocale) => void; className?: string}) {
  const t = useTranslations('Locale');
  const locale = useLocale() as AppLocale;
  const pathname = usePathname();
  const router = useRouter();
  return (
    <label className={cn('flex items-center gap-2 text-sm', className)}>
      <span className="sr-only">{t('label')}</span>
      <Select
        aria-label={t('label')}
        className="h-9 w-auto min-w-28 py-0 text-sm"
        value={locale}
        onChange={(event) => {
          const next = event.target.value as AppLocale;
          onChange?.(next);
          router.replace(pathname, {locale: next});
        }}
      >
        {locales.map((item) => (
          <option key={item} value={item} lang={htmlLang(item)}>{t(item)}</option>
        ))}
      </Select>
    </label>
  );
}

export function languageName(code: string, t: (key: 'en' | 'hi-IN' | 'pa-IN' | 'te-IN' | 'deccani-Latn') => string) {
  const map: Record<string, 'en' | 'hi-IN' | 'pa-IN' | 'te-IN' | 'deccani-Latn'> = {en: 'en', hi: 'hi-IN', pa: 'pa-IN', te: 'te-IN', deccani: 'deccani-Latn', 'hi-IN': 'hi-IN', 'pa-IN': 'pa-IN', 'te-IN': 'te-IN', 'deccani-Latn': 'deccani-Latn'};
  return map[code] ? t(map[code]) : code;
}
