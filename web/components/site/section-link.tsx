'use client';

import type {ComponentProps, MouseEvent} from 'react';
import {Link, usePathname} from '@/i18n/navigation';

/**
 * Link to a section of the home page (`/#how`). On the home page it scrolls there itself:
 * the router ignores a click when the URL already ends in the same hash, so a second click
 * after scrolling away would otherwise land in the wrong place. Elsewhere it navigates normally.
 */
export function SectionLink({href, onClick, ...props}: Omit<ComponentProps<typeof Link>, 'href'> & {href: `/#${string}`}) {
  const pathname = usePathname();
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || pathname !== '/' || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    const id = href.slice(2);
    const target = document.getElementById(id);
    if (!target) return;
    event.preventDefault();
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView({behavior: smooth ? 'smooth' : 'auto', block: 'start'});
    window.history.replaceState(window.history.state, '', `#${id}`);
  };
  return <Link href={href} onClick={handleClick} {...props} />;
}
