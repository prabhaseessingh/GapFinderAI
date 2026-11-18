import {GapReportView} from '@/components/app/gap-report';

export default async function Page({params}: {params: Promise<{workspaceId: string}>}) {
  return <GapReportView workspaceId={(await params).workspaceId} />;
}
