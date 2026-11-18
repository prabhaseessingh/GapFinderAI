import {SourceViewer} from '@/components/app/source-viewer';

export default async function SourcePage({params}: {params: Promise<{workspaceId: string; documentId: string}>}) {
  const {workspaceId, documentId} = await params;
  return <SourceViewer workspaceId={workspaceId} documentId={documentId} />;
}
