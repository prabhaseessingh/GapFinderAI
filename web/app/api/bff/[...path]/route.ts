import {NextRequest, NextResponse} from 'next/server';
import {checkRoute} from '@/lib/bff-routes';
import {createSupabaseServerClient} from '@/lib/supabase/server';

function envelope(status: number, code: string, message: string, requestId: string) {
  return NextResponse.json(
    {error: {code, message, requestId, retryable: status >= 500, nextAction: code === 'UNAUTHENTICATED' ? 'sign_in' : 'none'}},
    {status, headers: {'x-request-id': requestId}}
  );
}

async function forward(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const requestId = `req_${crypto.randomUUID().replaceAll('-', '')}`;
  const {path} = await context.params;
  const joined = path.join('/');
  const rawBody = ['GET', 'DELETE'].includes(request.method) ? '' : await request.text();
  const check = checkRoute(request.method, joined, rawBody, request.nextUrl.searchParams);
  if (!check.ok) return envelope(check.status, check.status === 404 ? 'NOT_FOUND' : 'VALIDATION_ERROR', check.message, requestId);

  const supabase = await createSupabaseServerClient();
  const {data: {session}} = await supabase.auth.getSession();
  if (!session) return envelope(401, 'UNAUTHENTICATED', 'Sign in is required.', requestId);
  const baseUrl = process.env.FASTAPI_INTERNAL_BASE_URL;
  if (!baseUrl) return envelope(503, 'PROVIDER_UNAVAILABLE', 'The API is not configured.', requestId);

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, '')}/${path.map(encodeURIComponent).join('/')}${check.query ? `?${check.query}` : ''}`, {
      method: request.method,
      headers: {
        authorization: `Bearer ${session.access_token}`,
        'x-request-id': requestId,
        ...(check.body ? {'content-type': 'application/json'} : {})
      },
      body: check.body,
      cache: 'no-store'
    });
    return new NextResponse(response.status === 204 ? null : response.body, {
      status: response.status,
      headers: {'content-type': response.headers.get('content-type') ?? 'application/json', 'x-request-id': requestId}
    });
  } catch {
    return envelope(503, 'PROVIDER_UNAVAILABLE', 'The GapFinder service is temporarily unavailable. Please try again shortly.', requestId);
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
