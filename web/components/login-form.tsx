'use client';

import {Loader2, LogIn, UserPlus} from 'lucide-react';
import {useSearchParams} from 'next/navigation';
import {useTranslations} from 'next-intl';
import {useState, type FormEvent} from 'react';
import {Button} from '@/components/ui/button';
import {Alert, Input, Label} from '@/components/ui/primitives';
import {Link, useRouter} from '@/i18n/navigation';
import {PRIVACY_POLICY_VERSION} from '@/lib/privacy';
import {createSupabaseBrowserClient} from '@/lib/supabase/browser';


export function LoginForm() {
  const t = useTranslations('Auth');
  const router = useRouter();
  const search = useSearchParams();
  const [mode, setMode] = useState<'signIn' | 'signUp'>(search.get('mode') === 'signup' ? 'signUp' : 'signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [accepted, setAccepted] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{tone: 'danger' | 'success' | 'info'; text: string} | null>(null);

  function nextPath() {
    const next = search.get('next') ?? '';
    // Only same-site app paths; strip the locale segment (the router adds the current one).
    const match = next.match(/^\/[A-Za-z-]+(\/app(?:\/[\w/-]*)?)$/);
    return match ? match[1] : '/app';
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    if (mode === 'signUp' && !accepted) return setMessage({tone: 'danger', text: t('acceptRequired')});
    setPending(true);
    const supabase = createSupabaseBrowserClient();
    const result =
      mode === 'signIn'
        ? await supabase.auth.signInWithPassword({email, password})
        : await supabase.auth.signUp({email, password, options: {data: {privacy_policy_version: PRIVACY_POLICY_VERSION}}});
    setPending(false);
    if (result.error) return setMessage({tone: 'danger', text: result.error.message});
    if (mode === 'signUp' && !result.data.session) return setMessage({tone: 'info', text: t('checkEmail')});
    router.replace(nextPath());
    router.refresh();
  }

  async function resend() {
    if (!email) return setMessage({tone: 'danger', text: t('enterEmailFirst')});
    const {error} = await createSupabaseBrowserClient().auth.resend({type: 'signup', email});
    setMessage(error ? {tone: 'danger', text: error.message} : {tone: 'success', text: t('resent')});
  }

  return (
    <div className="w-full max-w-md">
      <h1 className="text-3xl">{mode === 'signIn' ? t('signInTitle') : t('signUpTitle')}</h1>
      <p className="mt-2 text-muted">{mode === 'signIn' ? t('signInSubtitle') : t('signUpSubtitle')}</p>
      <form onSubmit={submit} className="mt-8 grid gap-5" noValidate={false}>
        <div className="grid gap-1.5">
          <Label htmlFor="email">{t('email')}</Label>
          <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="password">{t('password')}</Label>
          <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} aria-describedby="password-hint" autoComplete={mode === 'signIn' ? 'current-password' : 'new-password'} />
          {mode === 'signUp' && <p id="password-hint" className="text-xs text-muted">{t('passwordHint')}</p>}
        </div>
        {mode === 'signUp' && (
          <label className="flex items-start gap-3 text-sm">
            <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} required className="mt-1 size-4 shrink-0 accent-[#ec008c]" />
            <span>{t.rich('acceptPrivacy', {link: (chunks) => <Link href="/privacy" target="_blank" className="font-semibold text-brand underline underline-offset-4">{chunks}</Link>})}</span>
          </label>
        )}
        <Button type="submit" size="lg" disabled={pending}>
          {pending ? <Loader2 className="animate-spin" /> : mode === 'signIn' ? <LogIn /> : <UserPlus />}
          {pending ? t('working') : mode === 'signIn' ? t('signIn') : t('signUp')}
        </Button>
      </form>
      <div aria-live="polite" className="mt-4">{message && <Alert tone={message.tone}>{message.text}</Alert>}</div>
      <div className="mt-6 flex flex-col items-start gap-2 text-sm">
        <button type="button" className="font-semibold text-brand underline-offset-4 hover:underline" onClick={() => { setMode(mode === 'signIn' ? 'signUp' : 'signIn'); setMessage(null); }}>
          {mode === 'signIn' ? t('toSignUp') : t('toSignIn')}
        </button>
        {mode === 'signIn' && <button type="button" className="text-muted underline-offset-4 hover:text-ink hover:underline" onClick={() => void resend()}>{t('resend')}</button>}
      </div>
    </div>
  );
}
