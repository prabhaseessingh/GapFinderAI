import {QuizList} from '@/components/app/quiz-list';

export default async function QuizPage({params, searchParams}: {params: Promise<{workspaceId: string}>; searchParams: Promise<{retest?: string}>}) {
  const [{workspaceId}, query] = await Promise.all([params, searchParams]);
  return <QuizList workspaceId={workspaceId} openRetest={query.retest === '1'} />;
}
