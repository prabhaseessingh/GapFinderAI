import {z} from 'zod';
import {locales} from '@/i18n/config';

/**
 * BFF allowlist: the browser can reach only these FastAPI routes, and every mutation body is
 * parsed by a strict Zod schema first (unknown fields rejected). FastAPI re-validates with
 * Pydantic and owns authorization; this layer only narrows the attack surface.
 */
const uuid = z.uuid();
const locale = z.enum(locales);
const sha256 = z.string().regex(/^[a-f0-9]{64}$/);
const role = z.enum(['syllabus', 'textbook', 'notes', 'past_paper']);
const title = (max: number) => z.string().trim().min(1).max(max);

const none = z.undefined();
export const schemas = {
  createWorkspace: z.strictObject({title: title(120), selected_locale: locale}),
  renameWorkspace: z.strictObject({title: title(120)}),
  uploadIntent: z.strictObject({
    workspace_id: uuid,
    material_role: role,
    filename: z.string().min(1).max(255),
    mime_type: z.enum([
      'application/pdf',
      'text/plain',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]),
    byte_size: z.number().int().positive(),
    checksum_sha256: sha256
  }),
  confirmUpload: z.strictObject({checksum_sha256: sha256}),
  createTopic: z.strictObject({workspace_id: uuid, title: title(160), parent_id: uuid.nullable().optional()}),
  updateTopic: z.strictObject({
    title: title(160).optional(),
    parent_id: uuid.nullable().optional(),
    importance: z.number().int().min(1).max(5).optional(),
    reset_importance: z.boolean().optional()
  }),
  createQuiz: z.strictObject({
    workspace_id: uuid,
    kind: z.enum(['diagnostic', 'retest']).optional(),
    question_count: z.union([z.literal(5), z.literal(10), z.literal(15)]),
    topic_ids: z.array(uuid).max(200).nullable().optional(),
    timer_mode: z.enum(['untimed', 'timed']),
    time_limit_minutes: z.number().int().min(1).max(240).nullable().optional()
  }),
  studyPreferences: z.strictObject({
    exam_date: z.iso.date(),
    minutes_per_day: z.number().int().min(10).max(720),
    available_weekdays: z.array(z.enum(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])).min(1).max(7),
    timezone: z.string().min(1).max(64)
  }),
  completion: z.strictObject({done: z.boolean()}),
  deleteAccount: z.strictObject({confirm: z.literal('DELETE')}),
  saveResponse: z.strictObject({answer: z.union([z.string().max(5000), z.boolean(), z.null()])}),
  createExplanation: z.strictObject({
    workspace_id: uuid,
    question: z.string().trim().min(3).max(1000),
    locale,
    topic_id: uuid.nullable().optional(),
    origin: z.enum(['typed', 'voice', 'topic', 'report', 'question']).optional()
  }),
  transcribe: z.strictObject({
    workspace_id: uuid,
    locale,
    mime_type: z.enum(['audio/webm', 'audio/ogg', 'audio/mp4', 'audio/mpeg', 'audio/wav']),
    audio_base64: z.string().min(16).max(3_000_000).regex(/^[A-Za-z0-9+/]+=*$/)
  }),
  updateProfile: z.strictObject({
    timezone: z.string().min(1).max(64).optional(),
    display_name: z.string().max(80).optional(),
    selected_locale: locale.optional(),
    accept_privacy_policy_version: z.string().max(40).optional()
  })
} as const;

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
type Route = {method: Method; pattern: RegExp; body: z.ZodType; query?: z.ZodType};

const U = '[0-9a-fA-F-]{36}';
const r = (method: Method, path: string, body: z.ZodType = none, query?: z.ZodType): Route => ({
  method,
  pattern: new RegExp(`^${path.replaceAll(':id', U)}$`),
  body,
  query
});

export const routes: Route[] = [
  r('GET', 'profile'),
  r('PATCH', 'profile', schemas.updateProfile),
  r('POST', 'profile/delete-account', schemas.deleteAccount),
  r('GET', 'workspaces'),
  r('POST', 'workspaces', schemas.createWorkspace),
  r('POST', 'workspaces/demo'),
  r('PATCH', 'workspaces/:id', schemas.renameWorkspace),
  r('DELETE', 'workspaces/:id'),
  r('POST', 'documents/upload-intent', schemas.uploadIntent),
  r('POST', 'documents/:id/confirm', schemas.confirmUpload),
  r('POST', 'documents/:id/retry-processing'),
  r('GET', 'documents/workspace/:id'),
  r('GET', 'documents/:id/source'),
  r('GET', 'documents/:id/preview-url'),
  r('DELETE', 'documents/:id'),
  r('GET', 'topics/workspace/:id'),
  r('POST', 'topics/workspace/:id/propose'),
  r('POST', 'topics/workspace/:id/map-past-papers'),
  r('POST', 'topics/workspace/:id/approve-all'),
  r('GET', 'topics/workspace/:id/jobs/(propose|map_past_papers|segment_past_paper)'),
  r('GET', 'topics/workspace/:id/past-paper-questions'),
  r('POST', 'topics', schemas.createTopic),
  r('PATCH', 'topics/:id', schemas.updateTopic),
  r('POST', 'topics/:id/(approve|unapprove)'),
  r('GET', 'topics/:id/citations', none, z.strictObject({locale: locale.optional(), translate: z.enum(['true', 'false']).optional()})),
  r('DELETE', 'topics/:id'),
  r('POST', 'quizzes', schemas.createQuiz),
  r('GET', 'quizzes/workspace/:id'),
  r('GET', 'quizzes/:id'),
  r('POST', 'quizzes/:id/attempts'),
  r('GET', 'attempts/:id'),
  r('PUT', 'attempts/:id/responses/:id', schemas.saveResponse),
  r('POST', 'attempts/:id/submit'),
  r('POST', 'attempts/:id/evaluate'),
  r('GET', 'workspaces/:id/reports'),
  r('GET', 'workspaces/:id/reports/latest'),
  r('GET', 'reports/:id'),
  r('GET', 'workspaces/:id/plan'),
  r('PUT', 'workspaces/:id/study-preferences', schemas.studyPreferences),
  r('GET', 'workspaces/:id/plans'),
  r('GET', 'plans/:id'),
  r('PUT', 'plan-sessions/:id/completion', schemas.completion),
  r('GET', 'workspaces/:id/progress'),
  r('POST', 'explanations', schemas.createExplanation),
  r('GET', 'explanations/workspace/:id'),
  r('GET', 'explanations/:id', none, z.strictObject({locale: locale.optional()})),
  r('POST', 'explanations/:id/(audio|visual)'),
  r('GET', 'assets/:id'),
  r('POST', 'voice/transcribe', schemas.transcribe),
  r('GET', 'limits')
];

export type RouteCheck =
  | {ok: true; body: string | undefined; query: string}
  | {ok: false; status: 404 | 422; message: string};

export function checkRoute(method: string, path: string, rawBody: string, search: URLSearchParams): RouteCheck {
  const route = routes.find((item) => item.method === method && item.pattern.test(path));
  if (!route) return {ok: false, status: 404, message: 'Unknown API route.'};
  let parsedBody: unknown = undefined;
  if (rawBody.trim()) {
    try {
      parsedBody = JSON.parse(rawBody);
    } catch {
      return {ok: false, status: 422, message: 'The request body is not valid JSON.'};
    }
  }
  const body = route.body.safeParse(parsedBody);
  if (!body.success) return {ok: false, status: 422, message: 'The request is invalid.'};
  const queryObject = Object.fromEntries(search.entries());
  const query = (route.query ?? z.strictObject({})).safeParse(queryObject);
  if (!query.success) return {ok: false, status: 422, message: 'The request query is invalid.'};
  return {
    ok: true,
    body: body.data === undefined ? undefined : JSON.stringify(body.data),
    query: new URLSearchParams(query.data as Record<string, string>).toString()
  };
}
