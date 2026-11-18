import {QuizAttemptView} from '@/components/app/quiz-attempt';

export default async function AttemptPage({params}: {params: Promise<{workspaceId: string; attemptId: string}>}) {
  const {workspaceId, attemptId} = await params;
  return <QuizAttemptView workspaceId={workspaceId} attemptId={attemptId} />;
}
