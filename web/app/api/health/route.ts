import {NextResponse} from 'next/server';

export async function GET() {
  const baseUrl = process.env.FASTAPI_INTERNAL_BASE_URL;
  if (!baseUrl) return NextResponse.json({status: 'degraded', dependency: 'api-unconfigured'}, {status: 503});
  try {
    const response = await fetch(`${baseUrl}/health/ready`, {cache: 'no-store'});
    return NextResponse.json(await response.json(), {status: response.status});
  } catch { return NextResponse.json({status: 'degraded', dependency: 'api-unreachable'}, {status: 503}); }
}

