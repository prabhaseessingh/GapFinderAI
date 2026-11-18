/** Deep link into the Explain tab, pre-filled from a topic, report unit or missed question. */
export function explainHref(workspaceId: string, _title: string, topicId: string, origin: 'topic' | 'report' | 'question', question: string) {
  const query = new URLSearchParams({q: question.slice(0, 1000), topic: topicId, origin});
  return `/app/w/${workspaceId}/explain?${query.toString()}`;
}
