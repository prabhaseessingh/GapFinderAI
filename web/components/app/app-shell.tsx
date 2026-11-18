'use client';

import {ChevronDown, FolderOpen, LayoutGrid, Loader2, LogOut, ShieldCheck, Trash2, UserRound} from 'lucide-react';
import {useParams} from 'next/navigation';
import {useTranslations} from 'next-intl';
import {useEffect, useState, type ReactNode} from 'react';
import {Logo} from '@/components/brand/logo';
import {Button} from '@/components/ui/button';
import {Dialog, DialogContent, Input, Label, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger} from '@/components/ui/primitives';
import {Link, useRouter} from '@/i18n/navigation';
import {api, type Profile} from '@/lib/api';
import {keys, useApiMutation, useProfile, useWorkspaces} from '@/lib/queries';
import {createSupabaseBrowserClient} from '@/lib/supabase/browser';
import {LocaleSelect, useErrorText} from './shared';

function WorkspaceSwitcher() {
  const t = useTranslations('App');
  const params = useParams<{workspaceId?: string}>();
  const {data: workspaces = []} = useWorkspaces();
  const current = workspaces.find((item) => item.id === params.workspaceId);
  return (
    <Menu>
      <MenuTrigger asChild>
        <Button variant="ghost" size="sm" className="max-w-[46vw] sm:max-w-72" aria-label={t('switchWorkspace')}>
          <FolderOpen className="text-brand" />
          <span className="truncate">{current?.title ?? t('workspaces')}</span>
          <ChevronDown className="text-muted" />
        </Button>
      </MenuTrigger>
      <MenuContent align="start" className="max-h-96 w-72 overflow-y-auto">
        <MenuLabel>{t('switchWorkspace')}</MenuLabel>
        {workspaces.map((workspace) => (
          <MenuItem key={workspace.id} asChild>
            <Link href={`/app/w/${workspace.id}/materials`}>
              <FolderOpen className={workspace.id === current?.id ? 'text-brand' : 'text-muted'} />
              <span className="truncate">{workspace.title}</span>
            </Link>
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem asChild>
          <Link href="/app"><LayoutGrid />{t('allWorkspaces')}</Link>
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}

function PrivacyGate({profile}: {profile: Profile}) {
  const t = useTranslations('PrivacyGate');
  const tc = useTranslations('Common');
  const errorText = useErrorText();
  const [error, setError] = useState('');
  const accept = useApiMutation(
    () => api<Profile>('profile', {method: 'PATCH', body: {accept_privacy_policy_version: profile.current_privacy_policy_version}}),
    () => [keys.profile]
  );
  const open = profile.privacy_policy_version !== profile.current_privacy_policy_version;
  return (
    <Dialog open={open}>
      <DialogContent title={t('title')} closeLabel={tc('close')}>
        <p>{t('body', {version: profile.current_privacy_policy_version})}</p>
        <p className="mt-3"><Link href="/privacy" target="_blank" className="font-semibold text-brand underline-offset-4 hover:underline">{t('read')}</Link></p>
        {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <SignOutButton variant="secondary" label={t('signOut')} />
          <Button disabled={accept.isPending} onClick={() => accept.mutate(undefined, {onError: (e) => setError(errorText(e))})}>
            <ShieldCheck />{t('accept')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function SignOutButton({variant = 'ghost', label}: {variant?: 'ghost' | 'secondary'; label: string}) {
  const router = useRouter();
  return (
    <Button variant={variant} onClick={async () => {
      await createSupabaseBrowserClient().auth.signOut();
      router.replace('/');
      router.refresh();
    }}>
      <LogOut />{label}
    </Button>
  );
}

/** Immediate, irreversible deletion of the whole account (files first, then every record). */
function DeleteAccountDialog({open, onOpenChange}: {open: boolean; onOpenChange: (open: boolean) => void}) {
  const t = useTranslations('Account');
  const tc = useTranslations('Common');
  const errorText = useErrorText();
  const router = useRouter();
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function confirm() {
    setBusy(true);
    setError('');
    try {
      await api('profile/delete-account', {method: 'POST', body: {confirm: 'DELETE'}});
      await createSupabaseBrowserClient().auth.signOut();
      router.replace('/');
      router.refresh();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!busy) { onOpenChange(next); setTyped(''); setError(''); } }}>
      <DialogContent title={t('deleteTitle')} closeLabel={tc('close')}>
        <p>{t('deleteBody')}</p>
        <ul className="mt-3 list-disc pl-5 text-sm text-text">
          <li>{t('deleteItem1')}</li>
          <li>{t('deleteItem2')}</li>
          <li>{t('deleteItem3')}</li>
        </ul>
        <div className="mt-4 grid gap-1.5">
          <Label htmlFor="delete-confirm">{t('typeToConfirm')}</Label>
          <Input id="delete-confirm" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
        </div>
        {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="secondary" disabled={busy} onClick={() => onOpenChange(false)}>{tc('cancel')}</Button>
          <Button variant="danger" disabled={busy || typed.trim() !== 'DELETE'} onClick={() => void confirm()}>
            {busy ? <Loader2 className="animate-spin" /> : <Trash2 />}{t('deleteConfirm')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function AppShell({children, email}: {children: ReactNode; email: string}) {
  const t = useTranslations('Nav');
  const ta = useTranslations('Account');
  const router = useRouter();
  const {data: profile} = useProfile();
  const [deletingAccount, setDeletingAccount] = useState(false);
  const saveLocale = useApiMutation((locale: string) => api('profile', {method: 'PATCH', body: {selected_locale: locale}}), () => [keys.profile]);
  const saveZone = useApiMutation((timezone: string) => api('profile', {method: 'PATCH', body: {timezone}}), () => [keys.profile, keys.limits]);
  const {mutate: storeZone, isPending: storingZone} = saveZone;
  useEffect(() => {
    // Daily limits reset at the student's local midnight: remember the browser's zone once.
    if (!profile || profile.timezone || storingZone) return;
    try {
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (zone) storeZone(zone);
    } catch {
      /* no zone available: the server falls back to UTC */
    }
  }, [profile, storeZone, storingZone]);
  return (
    <div className="min-h-dvh bg-canvas">
      <header className="sticky top-0 z-40 border-b border-line bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-2 px-4 sm:gap-4 sm:px-6">
          <Link href="/app" className="shrink-0 rounded-sm"><Logo className="[&>span:last-child]:hidden sm:[&>span:last-child]:inline" /></Link>
          <span className="h-6 w-px bg-line" aria-hidden />
          <WorkspaceSwitcher />
          <div className="ml-auto flex items-center gap-2">
            <LocaleSelect className="hidden sm:flex" onChange={(locale) => saveLocale.mutate(locale)} />
            <Menu>
              <MenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={t('account')}><UserRound className="!size-5" /></Button>
              </MenuTrigger>
              <MenuContent className="w-64">
                <MenuLabel>{email}</MenuLabel>
                <div className="px-3 py-2 sm:hidden"><LocaleSelect onChange={(locale) => saveLocale.mutate(locale)} /></div>
                <MenuSeparator />
                <MenuItem onSelect={async () => {
                  await createSupabaseBrowserClient().auth.signOut();
                  router.replace('/');
                  router.refresh();
                }}>
                  <LogOut />{t('signOut')}
                </MenuItem>
                <MenuSeparator />
                <MenuItem danger onSelect={() => setDeletingAccount(true)}><Trash2 />{ta('deleteAccount')}</MenuItem>
              </MenuContent>
            </Menu>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-10">{children}</main>
      {profile && <PrivacyGate profile={profile} />}
      <DeleteAccountDialog open={deletingAccount} onOpenChange={setDeletingAccount} />
    </div>
  );
}
