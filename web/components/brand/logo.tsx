import {useId} from 'react';
import {cn} from '@/lib/utils';

/**
 * Original GapFinder mark: three stacked study cards with one missing slot, found by a lens.
 * Uses the brand gradient; `tone="light"` renders the wordmark for dark sections.
 */
export function LogoMark({className}: {className?: string}) {
  // Unique per instance: a shared id breaks when the first copy sits in a display:none subtree.
  const gradient = `gf-grad-${useId().replace(/:/g, '')}`;
  return (
    <svg viewBox="0 0 40 40" className={cn('size-9', className)} aria-hidden focusable="false">
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ec008c" />
          <stop offset=".55" stopColor="#a54686" />
          <stop offset="1" stopColor="#f4a623" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="11" fill={`url(#${gradient})`} />
      <rect x="8" y="9" width="17" height="4.5" rx="2.25" fill="#fff" />
      <rect x="8" y="17.75" width="7" height="4.5" rx="2.25" fill="#fff" opacity=".55" />
      <rect x="8" y="26.5" width="13" height="4.5" rx="2.25" fill="#fff" />
      <circle cx="25" cy="20" r="6" fill="none" stroke="#fff" strokeWidth="3" />
      <path d="M29.4 24.4 33 28" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({tone = 'dark', className}: {tone?: 'dark' | 'light'; className?: string}) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <LogoMark />
      <span className={cn('text-[19px] font-extrabold leading-none tracking-display', tone === 'dark' ? 'text-ink' : 'text-white')}>
        GapFinder<span className="text-brand-gradient"> AI</span>
      </span>
    </span>
  );
}
