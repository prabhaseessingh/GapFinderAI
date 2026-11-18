import {ProgressPanel} from '@/components/app/progress-panel';

export default async function Page({params}: {params: Promise<{workspaceId: string}>}) {
  return <ProgressPanel workspaceId={(await params).workspaceId} />;
}
