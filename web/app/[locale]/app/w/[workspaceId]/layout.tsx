import type {ReactNode} from 'react';
import {WorkspaceHeader} from '@/components/app/workspace-nav';

export default async function WorkspaceLayout({children, params}: {children: ReactNode; params: Promise<{workspaceId: string}>}) {
  const {workspaceId} = await params;
  return (
    <div className="grid gap-6">
      <WorkspaceHeader workspaceId={workspaceId} />
      {children}
    </div>
  );
}
