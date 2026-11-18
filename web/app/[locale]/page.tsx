import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {setRequestLocale} from 'next-intl/server';
import {Landing} from '@/components/site/landing';
import {SiteFooter, SiteHeader} from '@/components/site/chrome';

type TourShot = {key: string; src: string; width: number; height: number};

/** Screenshots are captured from the running app by `pnpm capture-tour` (never mock-ups). */
async function tourShots(): Promise<TourShot[]> {
  try {
    const manifest = await readFile(path.join(process.cwd(), 'public', 'tour', 'manifest.json'), 'utf8');
    return JSON.parse(manifest) as TourShot[];
  } catch {
    return [];
  }
}

export default async function Home({params}: {params: Promise<{locale: string}>}) {
  setRequestLocale((await params).locale);
  return (
    <>
      <SiteHeader />
      <Landing tour={await tourShots()} />
      <SiteFooter />
    </>
  );
}
