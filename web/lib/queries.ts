'use client';

import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {
  api,
  ApiError,
  type Citation,
  type Asset,
  type DocumentSource,
  type Explanation,
  type ExplanationSummary,
  type Limits,
  type GapReport,
  type PlanState,
  type PlanVersion,
  type ProgressData,
  type ReportVersion,
  type RevisionPlan,
  type JobStatus,
  type PastPaperQuestion,
  type QuizAttempt,
  type QuizSummary,
  type Profile,
  type StudyDocument,
  type Topic,
  type Workspace
} from './api';
import type {AppLocale} from '@/i18n/config';

export const keys = {
  profile: ['profile'] as const,
  workspaces: ['workspaces'] as const,
  documents: (id: string) => ['documents', id] as const,
  source: (id: string) => ['source', id] as const,
  topics: (id: string) => ['topics', id] as const,
  job: (id: string, job: string) => ['job', id, job] as const,
  questions: (id: string) => ['questions', id] as const,
  citations: (id: string, locale: string) => ['citations', id, locale] as const,
  quizzes: (id: string) => ['quizzes', id] as const,
  attempt: (id: string) => ['attempt', id] as const,
  report: (workspaceId: string) => ['report', workspaceId] as const,
  reportById: (id: string) => ['report-version', id] as const,
  reports: (workspaceId: string) => ['reports', workspaceId] as const,
  plan: (workspaceId: string) => ['plan', workspaceId] as const,
  planById: (id: string) => ['plan-version', id] as const,
  plans: (workspaceId: string) => ['plans', workspaceId] as const,
  progress: (workspaceId: string) => ['progress', workspaceId] as const,
  explanations: (workspaceId: string) => ['explanations', workspaceId] as const,
  explanation: (id: string, locale: string) => ['explanation', id, locale] as const,
  asset: (id: string) => ['asset', id] as const,
  limits: ['limits'] as const
};

/** Everything derived from an evaluated attempt (refresh after evaluation/availability changes). */
export const diagnosisKeys = (workspaceId: string) => [
  keys.report(workspaceId), keys.reports(workspaceId), keys.plan(workspaceId), keys.plans(workspaceId),
  keys.progress(workspaceId), keys.quizzes(workspaceId)
];

const PROCESSING = new Set(['uploaded', 'scanning', 'extracting', 'chunking', 'embedding', 'mapping']);

export const useProfile = () => useQuery({queryKey: keys.profile, queryFn: () => api<Profile>('profile')});
export const useWorkspaces = () => useQuery({queryKey: keys.workspaces, queryFn: () => api<Workspace[]>('workspaces')});

export function useDocuments(workspaceId: string) {
  return useQuery({
    queryKey: keys.documents(workspaceId),
    queryFn: () => api<StudyDocument[]>(`documents/workspace/${workspaceId}`),
    // Poll only while something is processing.
    refetchInterval: (query) => (query.state.data?.some((d) => PROCESSING.has(d.state)) ? 2500 : false)
  });
}

export const useDocumentSource = (documentId: string) =>
  useQuery({queryKey: keys.source(documentId), queryFn: () => api<DocumentSource>(`documents/${documentId}/source`)});

export const useTopics = (workspaceId: string) =>
  useQuery({queryKey: keys.topics(workspaceId), queryFn: () => api<Topic[]>(`topics/workspace/${workspaceId}`)});

export const usePastPaperQuestions = (workspaceId: string) =>
  useQuery({queryKey: keys.questions(workspaceId), queryFn: () => api<PastPaperQuestion[]>(`topics/workspace/${workspaceId}/past-paper-questions`)});

export function useJob(workspaceId: string, job: 'propose' | 'map_past_papers' | 'segment_past_paper') {
  const client = useQueryClient();
  return useQuery({
    queryKey: keys.job(workspaceId, job),
    queryFn: async () => {
      const status = await api<JobStatus>(`topics/workspace/${workspaceId}/jobs/${job}`);
      if (status.state === 'succeeded') {
        void client.invalidateQueries({queryKey: keys.topics(workspaceId)});
        void client.invalidateQueries({queryKey: keys.questions(workspaceId)});
      }
      return status;
    },
    refetchInterval: (query) => (['queued', 'running'].includes(query.state.data?.state ?? '') ? 2500 : false)
  });
}

/** Originals render immediately; translations (a provider call) arrive in a second query. */
export function useCitations(topicId: string | null, locale: AppLocale) {
  const originals = useQuery({
    queryKey: keys.citations(topicId ?? '', 'original'),
    queryFn: () => api<Citation[]>(`topics/${topicId}/citations?translate=false`),
    enabled: Boolean(topicId),
    staleTime: 5 * 60_000
  });
  const translated = useQuery({
    queryKey: keys.citations(topicId ?? '', locale),
    queryFn: () => api<Citation[]>(`topics/${topicId}/citations?locale=${encodeURIComponent(locale)}`),
    enabled: Boolean(topicId) && Boolean(originals.data?.length),
    staleTime: 5 * 60_000
  });
  return {
    data: translated.data ?? originals.data,
    isLoading: originals.isLoading,
    error: originals.error,
    translating: translated.isFetching && !translated.data
  };
}

/** Mutation helper that refreshes the given query keys afterwards. */
export function useApiMutation<TVars, TResult = unknown>(
  fn: (vars: TVars) => Promise<TResult>,
  invalidate: (vars: TVars) => readonly (readonly unknown[])[]
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: (_data, _error, vars) => Promise.all(invalidate(vars).map((queryKey) => client.invalidateQueries({queryKey})))
  });
}

export function useQuizzes(workspaceId: string) {
  return useQuery({
    queryKey: keys.quizzes(workspaceId),
    queryFn: () => api<QuizSummary[]>(`quizzes/workspace/${workspaceId}`),
    refetchInterval: (query) => (query.state.data?.some((q) => q.state === 'generating' || q.state === 'blueprint_draft'
      || q.latest_attempt_state === 'submitted' || q.latest_attempt_state === 'evaluating') ? 2500 : false)
  });
}

const EVALUATING = new Set(['submitted', 'evaluating']);

export function useAttempt(attemptId: string, workspaceId?: string) {
  const client = useQueryClient();
  return useQuery({
    queryKey: keys.attempt(attemptId),
    queryFn: async () => {
      const previous = client.getQueryData<QuizAttempt>(keys.attempt(attemptId));
      const attempt = await api<QuizAttempt>(`attempts/${attemptId}`);
      if (workspaceId && previous && previous.state !== attempt.state && attempt.state === 'evaluated') {
        diagnosisKeys(workspaceId).forEach((queryKey) => void client.invalidateQueries({queryKey}));
      }
      return attempt;
    },
    staleTime: Infinity,
    // Poll while the worker grades the attempt.
    refetchInterval: (query) => (EVALUATING.has(query.state.data?.state ?? '') ? 2500 : false)
  });
}

const noRetryOn404 = (count: number, error: unknown) => !(error instanceof ApiError && error.status === 404) && count < 2;

export const useLatestReport = (workspaceId: string) =>
  useQuery({queryKey: keys.report(workspaceId), queryFn: () => api<GapReport>(`workspaces/${workspaceId}/reports/latest`), retry: noRetryOn404});
export const useReportById = (reportId: string | null) =>
  useQuery({queryKey: keys.reportById(reportId ?? ''), queryFn: () => api<GapReport>(`reports/${reportId}`), enabled: Boolean(reportId), staleTime: Infinity});
export const useReportVersions = (workspaceId: string) =>
  useQuery({queryKey: keys.reports(workspaceId), queryFn: () => api<ReportVersion[]>(`workspaces/${workspaceId}/reports`)});
export const usePlanState = (workspaceId: string) =>
  useQuery({queryKey: keys.plan(workspaceId), queryFn: () => api<PlanState>(`workspaces/${workspaceId}/plan`)});
export const usePlanVersions = (workspaceId: string) =>
  useQuery({queryKey: keys.plans(workspaceId), queryFn: () => api<PlanVersion[]>(`workspaces/${workspaceId}/plans`)});
export const usePlanById = (planId: string | null) =>
  useQuery({queryKey: keys.planById(planId ?? ''), queryFn: () => api<RevisionPlan>(`plans/${planId}`), enabled: Boolean(planId), staleTime: Infinity});
export const useProgress = (workspaceId: string) =>
  useQuery({queryKey: keys.progress(workspaceId), queryFn: () => api<ProgressData>(`workspaces/${workspaceId}/progress`)});

const PENDING_EXPLANATION = new Set(['queued', 'running']);
const PENDING_ASSET = new Set(['queued', 'rendering']);

export const useExplanations = (workspaceId: string) =>
  useQuery({queryKey: keys.explanations(workspaceId), queryFn: () => api<ExplanationSummary[]>(`explanations/workspace/${workspaceId}`)});

export function useExplanation(id: string, locale: string) {
  const client = useQueryClient();
  return useQuery({
    queryKey: keys.explanation(id, locale),
    queryFn: async () => {
      const result = await api<Explanation>(`explanations/${id}?locale=${encodeURIComponent(locale)}`);
      if (!PENDING_EXPLANATION.has(result.state)) void client.invalidateQueries({queryKey: ['explanations', result.workspace_id]});
      return result;
    },
    refetchInterval: (query) => (PENDING_EXPLANATION.has(query.state.data?.state ?? 'queued') ? 2000 : false)
  });
}

/** Polls while rendering; a ready asset carries a short-lived signed URL. */
export const useAsset = (id: string, initialState: Asset['state']) =>
  useQuery({
    queryKey: keys.asset(id),
    queryFn: () => api<Asset>(`assets/${id}`),
    refetchInterval: (query) => (PENDING_ASSET.has(query.state.data?.state ?? initialState) ? 2500 : false),
    staleTime: 5 * 60_000
  });

export const useLimits = () => useQuery({queryKey: keys.limits, queryFn: () => api<Limits>('limits'), staleTime: 30_000});
