/**
 * GapFinder Worker (Workers AI behind a signed, server-only API).
 *
 *   POST /        one source-derived illustration (fixed image model)
 *   POST /embed   embeddings for up to 32 texts (fixed open-source model: Qwen3-Embedding-0.6B, Apache-2.0)
 *
 * Security contract:
 * - server-only: HMAC-SHA256 over "<unix seconds>.<raw body>" in X-GF-Signature, timestamp in X-GF-Timestamp
 * - stale (> 300 s skew) requests are rejected on every route
 * - illustrations are single-use (nonce kept in KV). Embeddings are not: replaying one only returns
 *   vectors for text the replayer already holds, and a KV write per search would exhaust the free
 *   KV write quota (1,000/day)
 * - models are fixed here; any extra field (e.g. a model id) or oversized input is rejected
 * - no CORS headers are ever sent, so browsers cannot call it usefully
 */

export const MODEL = '@cf/black-forest-labs/flux-1-schnell';
export const EMBED_MODEL = '@cf/qwen/qwen3-embedding-0.6b';
export const MAX_SKEW_SECONDS = 300;
export const MAX_PROMPT = 1000;
export const MAX_BODY = 4096;
export const MAX_EMBED_TEXTS = 32; // model limit
export const MAX_EMBED_CHARS = 8000; // per text; chunks are far smaller
export const MAX_EMBED_BODY = 300_000;
const ALLOWED_FIELDS = new Set(['explanation_id', 'nonce', 'prompt']);
const EMBED_FIELDS = new Set(['kind', 'texts']);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const NONCE_RE = /^[0-9a-f]{32}$/i;

const encoder = new TextEncoder();

function reject(status, code) {
  return new Response(JSON.stringify({error: code}), {status, headers: {'content-type': 'application/json'}});
}

export async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
  const signature = await crypto.subtle.sign('HMAC', key, encoder.encode(message));
  return [...new Uint8Array(signature)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function decodeImage(output) {
  // flux-1-schnell returns {image: base64 JPEG}
  const base64 = typeof output?.image === 'string' ? output.image : null;
  if (!base64) return null;
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/** Signature + freshness + size + JSON. Returns {body, timestamp} or {error: Response}. */
async function verify(request, env, now, maxBody) {
  if (request.method !== 'POST') return {error: reject(405, 'METHOD_NOT_ALLOWED')};
  if (!env.SHARED_SECRET) return {error: reject(500, 'NOT_CONFIGURED')};
  const timestamp = Number(request.headers.get('x-gf-timestamp'));
  const signature = (request.headers.get('x-gf-signature') || '').toLowerCase();
  if (!Number.isInteger(timestamp) || !signature) return {error: reject(401, 'UNSIGNED')};
  const raw = await request.text();
  if (raw.length > maxBody) return {error: reject(413, 'BODY_TOO_LARGE')};
  const expected = await hmacHex(env.SHARED_SECRET, `${timestamp}.${raw}`);
  if (!safeEqual(signature, expected)) return {error: reject(401, 'BAD_SIGNATURE')};
  if (Math.abs(now() - timestamp) > MAX_SKEW_SECONDS) return {error: reject(409, 'STALE_REQUEST')};
  try {
    const body = JSON.parse(raw);
    if (!body || typeof body !== 'object' || Array.isArray(body)) return {error: reject(400, 'BAD_JSON')};
    return {body, timestamp};
  } catch {
    return {error: reject(400, 'BAD_JSON')};
  }
}

export async function handleImage(request, env, now) {
  const {body, timestamp, error} = await verify(request, env, now, MAX_BODY);
  if (error) return error;
  if (Object.keys(body).some((k) => !ALLOWED_FIELDS.has(k))) return reject(400, 'UNKNOWN_FIELD');
  if (!UUID_RE.test(String(body.explanation_id)) || !NONCE_RE.test(String(body.nonce))) return reject(400, 'BAD_IDS');
  if (typeof body.prompt !== 'string' || !body.prompt.trim() || body.prompt.length > MAX_PROMPT) return reject(413, 'PROMPT_INVALID');

  const nonceKey = `nonce:${body.nonce}`;
  if (await env.NONCES.get(nonceKey)) return reject(409, 'REPLAY');
  await env.NONCES.put(nonceKey, String(timestamp), {expirationTtl: MAX_SKEW_SECONDS * 2});

  const output = await env.AI.run(MODEL, {prompt: body.prompt, steps: 4});
  const image = decodeImage(output);
  if (!image) return reject(502, 'NO_IMAGE');
  return new Response(image, {status: 200, headers: {'content-type': 'image/jpeg', 'cache-control': 'no-store'}});
}

export async function handleEmbed(request, env, now) {
  const {body, error} = await verify(request, env, now, MAX_EMBED_BODY);
  if (error) return error;
  if (Object.keys(body).some((k) => !EMBED_FIELDS.has(k))) return reject(400, 'UNKNOWN_FIELD');
  if (body.kind !== 'query' && body.kind !== 'document') return reject(400, 'BAD_KIND');
  const texts = body.texts;
  if (!Array.isArray(texts) || texts.length < 1 || texts.length > MAX_EMBED_TEXTS) return reject(413, 'TEXTS_INVALID');
  if (texts.some((t) => typeof t !== 'string' || !t.trim() || t.length > MAX_EMBED_CHARS)) return reject(413, 'TEXTS_INVALID');

  // Queries get the model's default retrieval instruction; documents are embedded as-is.
  const output = await env.AI.run(EMBED_MODEL, body.kind === 'query' ? {queries: texts} : {documents: texts});
  const data = output?.data;
  if (!Array.isArray(data) || data.length !== texts.length || data.some((v) => !Array.isArray(v) || v.length === 0)) {
    return reject(502, 'NO_EMBEDDING');
  }
  return new Response(JSON.stringify({data}), {status: 200, headers: {'content-type': 'application/json', 'cache-control': 'no-store'}});
}

export async function handle(request, env, now = () => Math.floor(Date.now() / 1000)) {
  const path = new URL(request.url).pathname;
  if (path === '/embed') return handleEmbed(request, env, now);
  if (path === '/') return handleImage(request, env, now);
  return reject(404, 'NOT_FOUND');
}

export default {
  fetch(request, env) {
    return handle(request, env);
  }
};
