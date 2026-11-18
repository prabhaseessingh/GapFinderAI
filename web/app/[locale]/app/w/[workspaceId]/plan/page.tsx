import {PlanPanel} from '@/components/app/plan-panel';

export default async function Page({params}: {params: Promise<{workspaceId: string}>}) {
  return <PlanPanel workspaceId={(await params).workspaceId} />;
}
