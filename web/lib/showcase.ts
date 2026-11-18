import type {GapLabel, PlanSession, QuizQuestion, Topic} from './api';

/**
 * Example content for marketing previews only (mirrors the demo workspace, Class 10 Science).
 * It is rendered through the real app components (TopicTree, ImportanceMeter, AnswerInput,
 * LabelBadge/MasteryBar, SessionLine, pipeline badges) so the landing page shows the actual UI.
 */
const base = {workspace_id: 'example', origin: 'proposal' as const, position: 0};
const t = (id: string, title: string, extra: Partial<Topic>): Topic => ({
  ...base,
  id,
  title,
  parent_id: null,
  status: 'approved',
  importance: 3,
  importance_source: 'default',
  importance_basis: {},
  citation_count: 1,
  past_paper_question_count: 0,
  ...extra
});

export const showcaseTopics: Topic[] = [
  t('u2', 'Unit 2 · Electricity', {importance: 5, importance_source: 'past_papers', citation_count: 2, past_paper_question_count: 5, importance_basis: {past_paper_questions: 5, weighted_marks: 18, years: [2024, 2025]}}),
  t('e1', "Ohm's law and resistance", {parent_id: 'u2', importance: 4, importance_source: 'past_papers', past_paper_question_count: 2, importance_basis: {past_paper_questions: 2, weighted_marks: 8, years: [2025]}}),
  t('e2', 'Resistors in series and parallel', {parent_id: 'u2', importance: 5, importance_source: 'past_papers', past_paper_question_count: 2, importance_basis: {past_paper_questions: 2, weighted_marks: 8, years: [2024, 2025]}}),
  t('u1', 'Unit 1 · Life Processes', {importance: 4, importance_source: 'past_papers', importance_basis: {past_paper_questions: 4, weighted_marks: 13, years: [2024, 2025]}, past_paper_question_count: 4}),
  t('l1', 'Photosynthesis', {parent_id: 'u1', status: 'draft', importance: 3, importance_source: 'past_papers', importance_basis: {past_paper_questions: 1, weighted_marks: 2, years: [2024]}, past_paper_question_count: 1}),
  t('u3', 'Unit 3 · Light', {importance: 3, importance_source: 'student', status: 'draft', citation_count: 3})
];

export const showcaseCitation = {
  file: 'class10-science-notes.txt',
  page: 1,
  heading: "Unit 2 › Ohm's law and resistance",
  quote: 'the current through a metallic conductor is directly proportional to the potential difference across its ends',
  translation: 'किसी धात्विक चालक से बहने वाली धारा उसके सिरों के बीच विभवांतर के समानुपाती होती है'
};

export const showcaseFiles = [
  {name: 'science-syllabus.pdf', role: 'syllabus' as const, state: 'ready' as const},
  {name: 'class10-science-notes.docx', role: 'notes' as const, state: 'embedding' as const},
  {name: 'board-paper-2025-scan.pdf', role: 'past_paper' as const, state: 'extracting' as const}
];

export const showcaseQuestion: QuizQuestion = {
  id: 'example-q',
  position: 1,
  topic_title: "Ohm's law and resistance",
  question_type: 'mcq',
  cognitive_level: 'understand',
  prompt: "The potential difference across a metallic conductor doubles while its temperature stays the same. What happens to the current?",
  options: [
    {id: 'A', text: 'It halves'},
    {id: 'B', text: 'It doubles'},
    {id: 'C', text: 'It stays the same'},
    {id: 'D', text: 'It becomes four times larger'}
  ],
  max_score: 1
};

export const showcaseUnits: {title: string; label: GapLabel; mastery: number | null; reason: 'score_weak' | 'score_medium' | 'score_strong' | 'limited_few_questions'}[] = [
  {title: 'Unit 2 · Electricity', label: 'weak', mastery: 38.5, reason: 'score_weak'},
  {title: 'Unit 1 · Life Processes', label: 'medium', mastery: 64, reason: 'score_medium'},
  {title: 'Unit 3 · Light', label: 'limited_evidence', mastery: null, reason: 'limited_few_questions'}
];

const session = (id: string, topic: string | null, activity: PlanSession['activity'], minutes: number, focus: string[], done = false): PlanSession =>
  ({id, day: '2026-11-18', sequence: 0, topic_id: topic ? id : null, topic_title: topic, focus, activity, minutes, completed_at: done ? '2026-11-18T10:00:00Z' : null});

export const showcaseSessions: PlanSession[] = [
  session('s1', 'Unit 2 · Electricity', 'study', 45, ['Resistors in series and parallel'], true),
  session('s2', 'Unit 1 · Life Processes', 'study', 30, ['Respiration']),
  session('s3', null, 'retest', 30, [])
];

export const showcaseExplanation = {
  question: "Why does the current double when the voltage doubles?",
  answer: "Ohm's law says the current through a metallic conductor is directly proportional to the potential difference across it, as long as its temperature does not change. So if the potential difference doubles, the current doubles too: V = I R, and R stays the same.",
  quote: showcaseCitation.quote,
  file: showcaseCitation.file
};

