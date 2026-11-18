import {describe, expect, it} from 'vitest';
import {checkRoute} from '@/lib/bff-routes';

const id = '0b2c6f1e-8d6a-4f3b-9a0c-1e2d3c4b5a69';
const q = new URLSearchParams();

describe('BFF allowlist', () => {
  it('allows known routes and normalises bodies', () => {
    const result = checkRoute('POST', 'workspaces', JSON.stringify({title: '  Bio  ', selected_locale: 'te-IN'}), q);
    expect(result).toEqual({ok: true, body: JSON.stringify({title: 'Bio', selected_locale: 'te-IN'}), query: ''});
    expect(checkRoute('GET', `topics/${id}/citations`, '', new URLSearchParams({locale: 'hi-IN'}))).toMatchObject({ok: true, query: 'locale=hi-IN'});
  });
  it('rejects unknown routes, methods and path shapes', () => {
    expect(checkRoute('GET', 'admin/users', '', q)).toMatchObject({ok: false, status: 404});
    expect(checkRoute('PUT', 'workspaces', '', q)).toMatchObject({ok: false, status: 404});
    expect(checkRoute('DELETE', 'workspaces/../profile', '', q)).toMatchObject({ok: false, status: 404});
  });
  it('validates quiz creation and autosave bodies', () => {
    const quiz = {workspace_id: id, question_count: 10, timer_mode: 'timed', time_limit_minutes: 15};
    expect(checkRoute('POST', 'quizzes', JSON.stringify(quiz), q)).toMatchObject({ok: true});
    expect(checkRoute('POST', 'quizzes', JSON.stringify({...quiz, question_count: 7}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('PUT', `attempts/${id}/responses/${id}`, JSON.stringify({answer: true}), q)).toMatchObject({ok: true});
    expect(checkRoute('PUT', `attempts/${id}/responses/${id}`, JSON.stringify({answer: {x: 1}}), q)).toMatchObject({ok: false, status: 422});
  });
  it('rejects unknown fields, bad values, stray bodies and stray query params', () => {
    expect(checkRoute('POST', 'workspaces', JSON.stringify({title: 'x', selected_locale: 'en', student_id: id}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('POST', 'workspaces', JSON.stringify({title: 'x', selected_locale: 'fr'}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('POST', `topics/${id}/approve`, JSON.stringify({x: 1}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('GET', 'workspaces', '', new URLSearchParams({debug: '1'}))).toMatchObject({ok: false, status: 422});
    expect(checkRoute('PATCH', `topics/${id}`, JSON.stringify({importance: 9}), q)).toMatchObject({ok: false, status: 422});
  });
  it('allows report/plan/progress routes with strict bodies', () => {
    for (const path of [`workspaces/${id}/reports`, `workspaces/${id}/reports/latest`, `reports/${id}`, `workspaces/${id}/plan`,
      `workspaces/${id}/plans`, `plans/${id}`, `workspaces/${id}/progress`]) {
      expect(checkRoute('GET', path, '', q)).toMatchObject({ok: true});
    }
    expect(checkRoute('POST', `attempts/${id}/evaluate`, '', q)).toMatchObject({ok: true});
    const prefs = {exam_date: '2026-12-20', minutes_per_day: 60, available_weekdays: ['mon', 'wed'], timezone: 'Asia/Kolkata'};
    expect(checkRoute('PUT', `workspaces/${id}/study-preferences`, JSON.stringify(prefs), q)).toMatchObject({ok: true});
    expect(checkRoute('PUT', `workspaces/${id}/study-preferences`, JSON.stringify({...prefs, exam_date: 'soon'}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('PUT', `workspaces/${id}/study-preferences`, JSON.stringify({...prefs, available_weekdays: ['someday']}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('PUT', `plan-sessions/${id}/completion`, JSON.stringify({done: true}), q)).toMatchObject({ok: true});
    expect(checkRoute('PUT', `plan-sessions/${id}/completion`, JSON.stringify({done: 'yes'}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('POST', 'quizzes', JSON.stringify({workspace_id: id, kind: 'retest', question_count: 5, timer_mode: 'untimed'}), q)).toMatchObject({ok: true});
    expect(checkRoute('POST', 'quizzes', JSON.stringify({workspace_id: id, kind: 'exam', question_count: 5, timer_mode: 'untimed'}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('DELETE', `reports/${id}`, '', q)).toMatchObject({ok: false, status: 404}); // history is append-only
  });
  it('allows Explain/voice/asset routes with strict bodies', () => {
    const ask = {workspace_id: id, question: 'Why is the sky blue?', locale: 'te-IN', topic_id: id, origin: 'topic'};
    expect(checkRoute('POST', 'explanations', JSON.stringify(ask), q)).toMatchObject({ok: true});
    expect(checkRoute('POST', 'explanations', JSON.stringify({...ask, origin: 'admin'}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('POST', 'explanations', JSON.stringify({...ask, model: 'gpt'}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('GET', `explanations/${id}`, '', new URLSearchParams({locale: 'hi-IN'}))).toMatchObject({ok: true});
    for (const kind of ['audio', 'visual']) expect(checkRoute('POST', `explanations/${id}/${kind}`, '', q)).toMatchObject({ok: true});
    expect(checkRoute('POST', `explanations/${id}/video`, '', q)).toMatchObject({ok: false, status: 404});
    expect(checkRoute('GET', `assets/${id}`, '', q)).toMatchObject({ok: true});
    expect(checkRoute('GET', 'limits', '', q)).toMatchObject({ok: true});
    const voice = {workspace_id: id, locale: 'en', mime_type: 'audio/webm', audio_base64: 'QUJDREVGR0hJSktMTU5PUA=='};
    expect(checkRoute('POST', 'voice/transcribe', JSON.stringify(voice), q)).toMatchObject({ok: true});
    expect(checkRoute('POST', 'voice/transcribe', JSON.stringify({...voice, mime_type: 'video/mp4'}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('POST', 'voice/transcribe', JSON.stringify({...voice, audio_base64: 'not base64!'}), q)).toMatchObject({ok: false, status: 422});
    expect(checkRoute('PATCH', 'profile', JSON.stringify({timezone: 'Asia/Kolkata'}), q)).toMatchObject({ok: true});
  });
});
