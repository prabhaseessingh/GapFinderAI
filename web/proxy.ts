import {createServerClient, type CookieOptions} from '@supabase/ssr';
import createIntlMiddleware from 'next-intl/middleware';
import {NextResponse, type NextRequest} from 'next/server';
import {routing} from './i18n/routing';

const intl = createIntlMiddleware(routing);
const APP_PATH = /^\/(en|hi-IN|pa-IN|te-IN|deccani-Latn)\/app(\/|$)/;

/**
 * Locale routing for every page. For the student app, the Supabase session is verified (and
 * refreshed) *before* locale handling, so a signed-out visitor is sent to sign-in with `next`.
 */
export default async function proxy(request: NextRequest) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key || !APP_PATH.test(request.nextUrl.pathname)) return intl(request);

  const refreshed: {name: string; value: string; options: CookieOptions}[] = [];
  const supabase = createServerClient(url, key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (values) => {
        values.forEach(({name, value}) => request.cookies.set(name, value));
        refreshed.push(...values);
      }
    }
  });
  const {data} = await supabase.auth.getUser();
  if (!data.user) {
    const locale = request.nextUrl.pathname.split('/')[1];
    const login = new URL(`/${locale}/login`, request.url);
    login.searchParams.set('next', request.nextUrl.pathname);
    return NextResponse.redirect(login);
  }
  const response = intl(request);
  refreshed.forEach(({name, value, options}) => response.cookies.set(name, value, options));
  return response;
}

export const config = {matcher: ['/((?!api|_next|_vercel|.*\\..*).*)']};
