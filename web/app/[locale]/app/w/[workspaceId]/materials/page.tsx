import {MaterialsPanel} from '@/components/app/materials-panel';

export default async function MaterialsPage({params}: {params: Promise<{workspaceId: string}>}) {
  return <MaterialsPanel workspaceId={(await params).workspaceId} />;
}
