import {ExplainPanel} from '@/components/app/explain-panel';

const ORIGINS = new Set(['typed', 'voice', 'topic', 'report', 'question']);

export default async function ExplainPage({params, searchParams}: {
  params: Promise<{workspaceId: string}>;
  searchParams: Promise<{q?: string; topic?: string; origin?: string}>;
}) {
  const [{workspaceId}, query] = await Promise.all([params, searchParams]);
  const origin = query.origin && ORIGINS.has(query.origin) ? (query.origin as 'topic' | 'report' | 'question') : 'typed';
  const topic = query.topic && /^[0-9a-f-]{36}$/i.test(query.topic) ? query.topic : null;
  return <ExplainPanel workspaceId={workspaceId} question={(query.q ?? '').slice(0, 1000)} topicId={topic} origin={origin} />;
}
