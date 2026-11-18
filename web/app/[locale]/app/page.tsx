import {setRequestLocale} from 'next-intl/server';
import {Dashboard} from '@/components/app/dashboard';

export default async function AppHome({params}: {params: Promise<{locale: string}>}) {
  setRequestLocale((await params).locale);
  return <Dashboard />;
}
