import {TopicsPanel} from '@/components/app/topics-panel';

export default async function TopicsPage({params}: {params: Promise<{workspaceId: string}>}) {
  return <TopicsPanel workspaceId={(await params).workspaceId} />;
}
