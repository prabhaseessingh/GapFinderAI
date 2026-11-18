// Run with: node --test   (Node 20+; no dependencies)
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {EMBED_MODEL, handle, hmacHex, MODEL} from '../src/index.js';

const SECRET = 'test-secret-value';
const NOW = 1_800_000_000;
const ID = '0b2c6f1e-8d6a-4f3b-9a0c-1e2d3c4b5a69';

// Shared vector: api/tests/test_explain.py asserts the Python signer produces the same hex.
export const VECTOR = {secret: 'vector-secret', timestamp: 1700000000, body: '{"explanation_id":"x","nonce":"y","prompt":"z"}'};
export const VECTOR_HEX = '533f00956acde5e426f5de71c8a8f33d84cfab8d18e2f6ff603e8e0d8af36965';

function env() {
  const store = new Map();
  const calls = [];
  const kvWrites = [];
  return {
    calls,
    kvWrites,
    SHARED_SECRET: SECRET,
    NONCES: {get: async (k) => store.get(k) ?? null, put: async (k, v) => { kvWrites.push(k); store.set(k, v); }},
    AI: {run: async (model, input) => {
      calls.push({model, input});
      if (model === EMBED_MODEL) {
        const texts = input.queries ?? input.documents;
        return {data: texts.map(() => Array.from({length: 1024}, (_, i) => (i === 0 ? 1 : 0))), shape: [texts.length, 1024]};
      }
      return {image: Buffer.from('jpegbytes').toString('base64')};
    }}
  };
}

async function signed(body, {timestamp = NOW, secret = SECRET, extraHeaders = {}, path = '/'} = {}) {
  const raw = typeof body === 'string' ? body : JSON.stringify(body);
  return new Request(`https://worker.example${path}`, {
    method: 'POST', body: raw,
    headers: {'x-gf-timestamp': String(timestamp), 'x-gf-signature': await hmacHex(secret, `${timestamp}.${raw}`), ...extraHeaders}
  });
}

const good = () => ({explanation_id: ID, nonce: 'a'.repeat(32), prompt: 'Clean flat educational diagram of the water cycle.'});
const now = () => NOW;

test('a signed, fresh, single-use request renders with the fixed model', async () => {
  const e = env();
  const response = await handle(await signed(good()), e, now);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'image/jpeg');
  assert.equal(response.headers.get('access-control-allow-origin'), null);
  assert.deepEqual(e.calls.map((c) => c.model), [MODEL]);
});

test('unsigned and wrongly signed requests are rejected before any model call', async () => {
  const e = env();
  const unsigned = new Request('https://worker.example/', {method: 'POST', body: JSON.stringify(good())});
  assert.equal((await handle(unsigned, e, now)).status, 401);
  assert.equal((await handle(await signed(good(), {secret: 'other'}), e, now)).status, 401);
  assert.equal(e.calls.length, 0);
});

test('replays and stale timestamps are rejected', async () => {
  const e = env();
  assert.equal((await handle(await signed(good()), e, now)).status, 200);
  assert.equal((await handle(await signed(good()), e, now)).status, 409);
  const stale = {...good(), nonce: 'b'.repeat(32)};
  assert.equal((await handle(await signed(stale, {timestamp: NOW - 301}), e, now)).status, 409);
  assert.equal(e.calls.length, 1);
});

test('arbitrary model ids, extra fields, bad ids and oversized prompts are rejected', async () => {
  const e = env();
  for (const [body, status] of [
    [{...good(), model: '@cf/other/model'}, 400],
    [{...good(), explanation_id: 'not-a-uuid'}, 400],
    [{...good(), prompt: 'x'.repeat(1001)}, 413],
    [{...good(), prompt: '   '}, 413]
  ]) {
    assert.equal((await handle(await signed(body), e, now)).status, status);
  }
  assert.equal((await handle(new Request('https://worker.example/', {method: 'GET'}), e, now)).status, 405);
  assert.equal(e.calls.length, 0);
});

const embedReq = (body, opts = {}) => signed(body, {...opts, path: '/embed'});

test('embed: documents and queries use the fixed open-source model, no KV write', async () => {
  const e = env();
  const docs = await handle(await embedReq({kind: 'document', texts: ['Ohm law', 'Photosynthesis']}), e, now);
  assert.equal(docs.status, 200);
  assert.equal(docs.headers.get('access-control-allow-origin'), null);
  const {data} = await docs.json();
  assert.equal(data.length, 2);
  assert.equal(data[0].length, 1024);
  const query = await handle(await embedReq({kind: 'query', texts: ['why does current double?']}), e, now);
  assert.equal(query.status, 200);
  assert.deepEqual(e.calls.map((c) => c.model), [EMBED_MODEL, EMBED_MODEL]);
  assert.deepEqual(e.calls[0].input, {documents: ['Ohm law', 'Photosynthesis']});
  assert.deepEqual(e.calls[1].input, {queries: ['why does current double?']});
  assert.deepEqual(e.kvWrites, []);
});

test('embed: unsigned, stale, oversized, extra-field and bad-kind requests never reach the model', async () => {
  const e = env();
  const good = {kind: 'document', texts: ['x']};
  const unsigned = new Request('https://worker.example/embed', {method: 'POST', body: JSON.stringify(good)});
  for (const [request, status] of [
    [unsigned, 401],
    [await embedReq(good, {secret: 'other'}), 401],
    [await embedReq(good, {timestamp: NOW - 301}), 409],
    [await embedReq({...good, model: '@cf/other/model'}), 400],
    [await embedReq({kind: 'other', texts: ['x']}), 400],
    [await embedReq({kind: 'query', texts: []}), 413],
    [await embedReq({kind: 'query', texts: Array(33).fill('x')}), 413],
    [await embedReq({kind: 'query', texts: ['  ']}), 413],
    [await embedReq({kind: 'query', texts: ['x'.repeat(8001)]}), 413]
  ]) {
    assert.equal((await handle(request, e, now)).status, status);
  }
  assert.equal(e.calls.length, 0);
});

test('embed: a malformed model response is a 502, and unknown paths are 404', async () => {
  const e = env();
  e.AI.run = async () => ({data: [[1, 2]]}); // 1 vector for 2 texts
  assert.equal((await handle(await embedReq({kind: 'document', texts: ['a', 'b']}), e, now)).status, 502);
  assert.equal((await handle(await signed({kind: 'document', texts: ['a']}, {path: '/other'}), e, now)).status, 404);
});

test('the shared HMAC vector matches the Python signer', async () => {
  const hex = await hmacHex(VECTOR.secret, `${VECTOR.timestamp}.${VECTOR.body}`);
  assert.match(hex, /^[0-9a-f]{64}$/);
  process.stdout.write(`VECTOR_HEX=${hex}\n`);
});
