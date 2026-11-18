'use client';

import {ArrowRight, FlaskConical, FolderOpen, MoreHorizontal, Pencil, Plus, Trash2} from 'lucide-react';
import {motion, useReducedMotion} from 'framer-motion';
import {useFormatter, useLocale, useNow, useTranslations} from 'next-intl';
import {useState, type FormEvent} from 'react';
import {Button} from '@/components/ui/button';
import {Alert, Badge, Card, Dialog, DialogContent, Input, Label, Menu, MenuContent, MenuItem, MenuTrigger, Skeleton} from '@/components/ui/primitives';
import {Link, useRouter} from '@/i18n/navigation';
import {api, type Workspace} from '@/lib/api';
import {keys, useApiMutation, useWorkspaces} from '@/lib/queries';
import {useErrorText} from './shared';

export function NameDialog({open, onOpenChange, title, description, label, placeholder, initial, submitLabel, pendingLabel, onSubmit, maxLength = 120}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  label: string;
  placeholder?: string;
  initial?: string;
  submitLabel: string;
  pendingLabel?: string;
  maxLength?: number;
  onSubmit: (value: string) => Promise<unknown>;
}) {
  const tc = useTranslations('Common');
  const errorText = useErrorText();
  const [value, setValue] = useState(initial ?? '');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!value.trim()) return;
    setPending(true);
    setError('');
    try {
      await onSubmit(value.trim());
      onOpenChange(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPending(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={(next) => { onOpenChange(next); if (next) { setValue(initial ?? ''); setError(''); } }}>
      <DialogContent title={title} description={description} closeLabel={tc('close')}>
        <form onSubmit={submit} className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="name-field">{label}</Label>
            <Input id="name-field" autoFocus value={value} maxLength={maxLength} placeholder={placeholder} onChange={(e) => setValue(e.target.value)} />
          </div>
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <div className="flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>{tc('cancel')}</Button>
            <Button type="submit" disabled={pending || !value.trim()}>{pending ? pendingLabel ?? tc('loading') : submitLabel}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ConfirmDialog({open, onOpenChange, title, body, confirmLabel, pendingLabel, onConfirm}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: string;
  confirmLabel: string;
  pendingLabel?: string;
  onConfirm: () => Promise<unknown>;
}) {
  const tc = useTranslations('Common');
  const errorText = useErrorText();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  return (
    <Dialog open={open} onOpenChange={(next) => { onOpenChange(next); setError(''); }}>
      <DialogContent title={title} closeLabel={tc('close')}>
        <p>{body}</p>
        {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="secondary" onClick={() => onOpenChange(false)}>{tc('cancel')}</Button>
          <Button
            variant="danger"
            disabled={pending}
            onClick={async () => {
              setPending(true);
              try {
                await onConfirm();
                onOpenChange(false);
              } catch (e) {
                setError(errorText(e));
              } finally {
                setPending(false);
              }
            }}
          >
            <Trash2 />{pending ? pendingLabel ?? tc('loading') : confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function WorkspaceCard({workspace, index}: {workspace: Workspace; index: number}) {
  const t = useTranslations('Dashboard');
  const tc = useTranslations('Common');
  const format = useFormatter();
  const now = useNow({updateInterval: 60_000});
  const reduce = useReducedMotion();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const rename = useApiMutation((title: string) => api(`workspaces/${workspace.id}`, {method: 'PATCH', body: {title}}), () => [keys.workspaces]);
  const remove = useApiMutation(() => api(`workspaces/${workspace.id}`, {method: 'DELETE'}), () => [keys.workspaces]);
  return (
    <motion.li initial={reduce ? false : {opacity: 0, y: 14}} animate={{opacity: 1, y: 0}} transition={{delay: Math.min(index, 8) * 0.05, duration: 0.4}}>
      <Card className="group relative flex h-full flex-col p-5 transition-shadow duration-300 hover:shadow-float">
        <div className="flex items-start justify-between gap-3">
          <span className="grid size-11 place-items-center rounded-md bg-pink-100 text-brand"><FolderOpen className="size-5" /></span>
          <Menu>
            <MenuTrigger asChild>
              <Button variant="ghost" size="icon" className="relative z-10" aria-label={`${tc('more')}: ${workspace.title}`}><MoreHorizontal /></Button>
            </MenuTrigger>
            <MenuContent>
              <MenuItem onSelect={() => setRenaming(true)}><Pencil />{tc('rename')}</MenuItem>
              <MenuItem danger onSelect={() => setDeleting(true)}><Trash2 />{tc('delete')}</MenuItem>
            </MenuContent>
          </Menu>
        </div>
        {workspace.demo_source && <Badge tone="info" className="mt-4 w-fit"><FlaskConical className="size-3" />{t('demoBadge')}</Badge>}
        <h2 className="mt-4 line-clamp-2 text-lg">
          <Link href={`/app/w/${workspace.id}/materials`} className="after:absolute after:inset-0 after:content-[''] focus-visible:outline-none">{workspace.title}</Link>
        </h2>
        <p className="mt-1 text-sm text-muted">{t('updated', {date: format.relativeTime(new Date(workspace.updated_at), now)})}</p>
        <span className="mt-auto inline-flex items-center gap-1 pt-5 text-sm font-semibold text-brand">
          {t('open')}<ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
        </span>
      </Card>
      <NameDialog open={renaming} onOpenChange={setRenaming} title={t('renameTitle')} label={t('name')} initial={workspace.title} submitLabel={tc('save')} onSubmit={(title) => rename.mutateAsync(title)} />
      <ConfirmDialog open={deleting} onOpenChange={setDeleting} title={t('deleteTitle', {title: workspace.title})} body={t('deleteBody')} confirmLabel={t('deleteConfirm')} pendingLabel={t('deleting')} onConfirm={() => remove.mutateAsync(undefined)} />
    </motion.li>
  );
}

export function Dashboard() {
  const t = useTranslations('Dashboard');
  const ta = useTranslations('App');
  const tc = useTranslations('Common');
  const locale = useLocale();
  const router = useRouter();
  const {data, isLoading, error, refetch} = useWorkspaces();
  const errorText = useErrorText();
  const [creating, setCreating] = useState(false);
  const create = useApiMutation(
    (title: string) => api<Workspace>('workspaces', {method: 'POST', body: {title, selected_locale: locale}}),
    () => [keys.workspaces]
  );
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl sm:text-4xl">{t('title')}</h1>
          <p className="mt-2 text-muted">{t('subtitle')}</p>
        </div>
        <Button onClick={() => setCreating(true)}><Plus />{t('create')}</Button>
      </div>
      <div className="mt-8">
        {isLoading && <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-48" />)}</ul>}
        {error && <Alert tone="danger" title={ta('loadError')} action={<Button size="sm" variant="secondary" onClick={() => refetch()}>{tc('retry')}</Button>}>{errorText(error)}</Alert>}
        {data && data.length === 0 && (
          <Card className="grid place-items-center px-6 py-16 text-center">
            <span className="grid size-16 place-items-center rounded-full bg-pink-100 text-brand"><FolderOpen className="size-7" /></span>
            <h2 className="mt-5 text-xl">{t('empty')}</h2>
            <p className="mt-2 max-w-md text-muted">{t('emptyBody')}</p>
            <Button className="mt-6" onClick={() => setCreating(true)}><Plus />{t('create')}</Button>
          </Card>
        )}
        {data && data.length > 0 && (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.map((workspace, index) => <WorkspaceCard key={workspace.id} workspace={workspace} index={index} />)}
          </ul>
        )}
      </div>
      <NameDialog
        open={creating}
        onOpenChange={setCreating}
        title={t('createTitle')}
        description={t('createDescription')}
        label={t('name')}
        placeholder={t('namePlaceholder')}
        submitLabel={t('create')}
        pendingLabel={t('creating')}
        onSubmit={async (title) => {
          const workspace = await create.mutateAsync(title);
          router.push(`/app/w/${workspace.id}/materials`);
        }}
      />
    </>
  );
}
