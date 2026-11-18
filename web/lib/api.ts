'use client';

import type {AppLocale} from '@/i18n/config';

export type MaterialRole = 'syllabus' | 'textbook' | 'notes' | 'past_paper';
export type DocumentState = 'uploaded' | 'scanning' | 'extracting' | 'chunking' | 'embedding' | 'mapping' | 'ready' | 'failed';

export type Profile = {
  id: string;
  display_name: string | null;
  selected_locale: AppLocale;
  privacy_accepted_at: string | null;
  privacy_policy_version: string | null;
  timezone: string | null;
  current_privacy_policy_version: string;
};
export type Workspace = {id: string; title: string; selected_locale: AppLocale; demo_source: string | null; created_at: string; updated_at: string};
export type StudyDocument = {
  id: string;
  workspace_id: string;
  material_role: MaterialRole;
  filename: string;
  mime_type: string;
  byte_size: number;
  version: number;
  state: DocumentState;
  failure_code: string | null;
  processing_attempts: number;
  page_count: number | null;
  created_at: string;
  updated_at: string;
};
export type SourceChunk = {id: string; chunk_index: number; page_start: number | null; page_end: number | null; heading_path: string[]; text: string; source_language: string};
export type DocumentSource = {document: StudyDocument; chunks: SourceChunk[]};
export type Topic = {
  id: string;
  workspace_id: string;
  parent_id: string | null;
  title: string;
  status: 'draft' | 'approved';
  importance: number;
  importance_source: 'default' | 'past_papers' | 'student';
  importance_basis: {past_paper_questions?: number; weighted_marks?: number; years?: number[]; workspace_past_paper_questions?: number};
  position: number;
  origin: 'proposal' | 'manual';
  citation_count: number;
  past_paper_question_count: number;
};
export type Citation = {
  chunk_id: string;
  document_id: string;
  document_name: string;
  document_version: number;
  material_role: MaterialRole;
  page_start: number | null;
  page_end: number | null;
  heading_path: string[];
  original_quote: string;
  source_language: string;
  translated_quote: string | null;
  translation_locale: string | null;
  score: number;
};
export type JobStatus = {task: string; state: 'none' | 'queued' | 'running' | 'succeeded' | 'failed'; error_code: string | null; updated_at: string | null; result: Record<string, unknown>};
export type PastPaperQuestion = {id: string; document_id: string; document_name: string; label: string | null; question_text: string; page: number | null; marks: number | null; year: number | null; topic_ids: string[]};
export type UploadIntent = {document_id: string; storage_path: string; tus_endpoint: string; bucket: string};

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: {method?: string; body?: unknown}): Promise<T> {
  const response = await fetch(`/api/bff/${path}`, {
    method: init?.method ?? 'GET',
    headers: init?.body === undefined ? undefined : {'content-type': 'application/json'},
    body: init?.body === undefined ? undefined : JSON.stringify(init.body)
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      payload?.error?.code ?? 'INTERNAL_ERROR',
      payload?.error?.message ?? `Request failed (${response.status}).`,
      payload?.error?.requestId
    );
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export type QuestionType = 'mcq' | 'true_false' | 'short_answer';
export type QuizSummary = {
  id: string;
  workspace_id: string;
  state: 'blueprint_draft' | 'generating' | 'ready' | 'generation_failed';
  kind: 'diagnostic' | 'retest';
  question_count: number;
  locale: string;
  timer_mode: 'untimed' | 'timed';
  time_limit_seconds: number | null;
  failure_code: string | null;
  created_at: string;
  not_tested: {topic_id: string; title: string; reason: 'no_evidence' | 'question_budget'}[];
  unit_titles: string[];
  latest_attempt_id: string | null;
  latest_attempt_state: string | null;
  latest_attempt_score: number | null;
  progress_done: number;
};
export type QuizQuestion = {
  id: string;
  position: number;
  topic_title: string;
  question_type: QuestionType;
  cognitive_level: 'recall' | 'understand' | 'apply';
  prompt: string;
  options: {id: string; text: string}[] | null;
  max_score: number;
  // review-only fields (present after submission)
  correct_option_id?: string | null;
  correct_boolean?: boolean | null;
  model_answer?: string | null;
  rubric?: {criterion: string; points: number}[];
  explanation?: string | null;
  citations?: Citation[];
  // evaluation (present once graded)
  score?: number | null;
  verdict?: Verdict | null;
  evaluator?: 'deterministic' | 'groq' | null;
  confidence?: number | null;
  feedback?: string | null;
  criteria?: {index: number; criterion: string; points: number; awarded: number; met: boolean}[];
  evaluation_citations?: Citation[];
};
export type Verdict = 'correct' | 'partial' | 'incorrect' | 'unanswered' | 'insufficient_evidence';
export type AttemptAnswer = string | boolean | null;
export type QuizAttempt = {
  id: string;
  quiz_id: string;
  workspace_id: string;
  state: 'in_progress' | 'submitted' | 'evaluating' | 'evaluated' | 'evaluation_failed';
  started_at: string;
  deadline_at: string | null;
  submitted_at: string | null;
  submit_reason: 'student' | 'time_limit' | null;
  elapsed_seconds: number | null;
  server_now: string;
  timer_mode: 'untimed' | 'timed';
  questions: QuizQuestion[];
  answers: Record<string, AttemptAnswer>;
  quiz_kind: 'diagnostic' | 'retest';
  failure_code: string | null;
  score: number | null;
  max_score: number | null;
  report_id: string | null;
};

export type GapLabel = 'weak' | 'medium' | 'strong' | 'limited_evidence';
export type CognitiveLevel = 'recall' | 'understand' | 'apply';
export type UnitFacts = {
  latest_correct?: number;
  latest_max?: number;
  latest_questions?: number;
  all_questions?: number;
  attempts?: number;
  coverage?: number;
  level_accuracy?: Partial<Record<CognitiveLevel, number>>;
  weak_levels?: CognitiveLevel[];
  subtopics?: {title: string; accuracy: number}[];
  limited_reason?: 'not_tested' | 'few_questions' | 'low_confidence' | null;
};
export type MissedQuestion = {
  question_id: string;
  attempt_id: string;
  prompt: string;
  question_type: QuestionType;
  cognitive_level: CognitiveLevel;
  topic_title: string;
  score: number | null;
  max_score: number;
  verdict: Verdict | null;
  feedback: string | null;
  citations: Citation[];
};
export type UnitReport = {
  topic_id: string | null;
  title: string;
  position: number;
  label: GapLabel;
  mastery: number | null;
  confidence: number;
  priority: number;
  importance: number;
  importance_source: Topic['importance_source'] | null;
  evaluated_questions: number;
  facts: UnitFacts;
  reasons: string[];
  action: 'study' | 'review' | 'retest' | 'gather_evidence';
  missed: MissedQuestion[];
  previous_label: GapLabel | null;
  previous_mastery: number | null;
};
export type GapReport = {
  id: string;
  workspace_id: string;
  version: number;
  attempt_id: string | null;
  quiz_kind: 'diagnostic' | 'retest' | null;
  policy_version: string;
  created_at: string;
  summary: {overall_score?: number | null; questions?: number; answered?: number; labels?: Partial<Record<GapLabel, number>>};
  units: UnitReport[];
  previous_report_id: string | null;
};
export type ReportVersion = {id: string; version: number; created_at: string; attempt_id: string | null; quiz_kind: string | null; overall_score: number | null};
export type Weekday = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun';
export type StudyPreferences = {id: string; created_at: string; exam_date: string; minutes_per_day: number; available_weekdays: Weekday[]; timezone: string};
export type PlanSession = {id: string; day: string; sequence: number; topic_id: string | null; topic_title: string | null; focus: string[]; activity: 'study' | 'review' | 'retest'; minutes: number; completed_at: string | null};
export type RevisionPlan = {
  id: string;
  version: number;
  report_id: string;
  report_version: number;
  preferences: StudyPreferences;
  status: 'feasible' | 'shortfall';
  demand_minutes: number;
  scheduled_minutes: number;
  available_minutes: number;
  shortfall: {topic_id: string; title: string; label: GapLabel; minutes: number}[];
  policy_version: string;
  created_at: string;
  sessions: PlanSession[];
  is_latest: boolean;
};
export type PlanVersion = {id: string; version: number; report_version: number; status: string; created_at: string};
export type PlanState = {preferences: StudyPreferences | null; plan: RevisionPlan | null; next_action: 'take_diagnostic' | 'set_availability' | 'none'};
export type ProgressData = {
  reports: {report_id: string; version: number; created_at: string; quiz_kind: string | null; overall_score: number | null; units: Record<string, number | null>; labels: Record<string, GapLabel>}[];
  unit_titles: string[];
  completion: {sessions_planned: number; sessions_completed: number; minutes_planned: number; minutes_completed: number};
};

export type ExplanationOrigin = 'typed' | 'voice' | 'topic' | 'report' | 'question';
export type Asset = {
  id: string;
  explanation_id: string;
  kind: 'audio' | 'illustration' | 'source_figure';
  state: 'queued' | 'rendering' | 'ready' | 'not_eligible' | 'failed';
  failure_code: string | null;
  mime_type: string | null;
  url: string | null;
  meta: Record<string, unknown>;
};
export type Explanation = {
  id: string;
  workspace_id: string;
  topic_id: string | null;
  question: string;
  locale: string;
  origin: ExplanationOrigin;
  state: 'queued' | 'running' | 'answered' | 'insufficient' | 'failed';
  answer: string | null;
  citations: Citation[];
  next_action: string | null;
  failure_code: string | null;
  created_at: string;
  assets: Asset[];
  voice_available: boolean;
  voice_reason: 'not_configured' | 'language_unsupported' | 'not_answered' | null;
  visual_available: boolean;
  visual_reason: 'not_answered' | 'source_figure_only' | null;
};
export type ExplanationSummary = {id: string; question: string; state: string; origin: ExplanationOrigin; created_at: string};
export type Limits = {timezone: string; actions: {action: 'diagnostic' | 'explain' | 'voice' | 'visual'; used: number; limit: number; resets_at: string}[]};
