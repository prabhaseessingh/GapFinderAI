import {clsx, type ClassValue} from 'clsx';
import {twMerge} from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatBytes(bytes: number, locale: string) {
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat(safeLocale(locale), {maximumFractionDigits: unit ? 1 : 0}).format(value)} ${units[unit]}`;
}

/** Intl has no data for the project-specific Deccani locale; format it like Indian English. */
export function safeLocale(locale: string) {
  return locale === 'deccani-Latn' ? 'en-IN' : locale;
}
