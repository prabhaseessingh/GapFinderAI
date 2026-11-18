'use client';

import {cva, type VariantProps} from 'class-variance-authority';
import {X} from 'lucide-react';
import {
  Accordion as AccordionPrimitive,
  Dialog as DialogPrimitive,
  DropdownMenu as MenuPrimitive,
  Progress as ProgressPrimitive,
  Tooltip as TooltipPrimitive
} from 'radix-ui';
import type {ComponentProps, ReactNode} from 'react';
import {cn} from '@/lib/utils';

/* ---------- Card ---------- */
export function Card({className, ...props}: ComponentProps<'div'>) {
  return <div className={cn('rounded-lg border border-line bg-surface shadow-card', className)} {...props} />;
}

/* ---------- Inputs ---------- */
const fieldClass =
  'w-full rounded-sm border border-line-strong bg-surface px-3.5 text-[15px] text-ink placeholder:text-muted transition-colors focus:border-brand focus:outline-none focus-visible:outline-none focus:ring-4 focus:ring-brand/15 disabled:opacity-60';

export function Input({className, ...props}: ComponentProps<'input'>) {
  return <input className={cn(fieldClass, 'h-11', className)} {...props} />;
}

export function Select({className, ...props}: ComponentProps<'select'>) {
  return <select className={cn(fieldClass, 'h-11 pr-8', className)} {...props} />;
}

export function Label({className, ...props}: ComponentProps<'label'>) {
  return <label className={cn('text-sm font-semibold text-ink', className)} {...props} />;
}

/* ---------- Badge ---------- */
export const badgeVariants = cva('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold leading-5', {
  variants: {
    tone: {
      neutral: 'bg-soft text-text',
      brand: 'bg-pink-100 text-brand',
      success: 'bg-success-50 text-success',
      warning: 'bg-warning-50 text-warning',
      danger: 'bg-danger-50 text-danger',
      info: 'bg-cyan-50 text-[#0369a1]'
    }
  },
  defaultVariants: {tone: 'neutral'}
});
export function Badge({className, tone, ...props}: ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({tone}), className)} {...props} />;
}

/* ---------- Alert ---------- */
export function Alert({tone = 'info', title, children, action, className}: {
  tone?: 'info' | 'success' | 'warning' | 'danger';
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const tones = {
    info: 'border-cyan/30 bg-cyan-50',
    success: 'border-success/30 bg-success-50',
    warning: 'border-amber/40 bg-warning-50',
    danger: 'border-danger/30 bg-danger-50'
  };
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex flex-wrap items-start justify-between gap-3 rounded-md border px-4 py-3 text-sm', tones[tone], className)}>
      <div className="min-w-0">
        {title && <p className="font-semibold text-ink">{title}</p>}
        {children && <div className="text-text">{children}</div>}
      </div>
      {action}
    </div>
  );
}

/* ---------- Skeleton / Progress ---------- */
export function Skeleton({className}: {className?: string}) {
  return <div aria-hidden className={cn('animate-pulse rounded-md bg-soft', className)} />;
}

export function Progress({value, label, className}: {value: number; label: string; className?: string}) {
  return (
    <ProgressPrimitive.Root value={value} aria-label={label} className={cn('relative h-2 w-full overflow-hidden rounded-full bg-soft', className)}>
      <ProgressPrimitive.Indicator className="h-full bg-brand-gradient-vivid transition-transform duration-300" style={{transform: `translateX(-${100 - value}%)`}} />
    </ProgressPrimitive.Root>
  );
}

/* ---------- Dialog ---------- */
export const Dialog = DialogPrimitive.Root;

export function DialogContent({title, description, children, className, closeLabel, side}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  className?: string;
  closeLabel: string;
  side?: 'right';
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/40 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in" />
      <DialogPrimitive.Content
        className={cn(
          'fixed z-50 bg-surface shadow-float focus:outline-none',
          side === 'right'
            ? 'inset-y-0 right-0 flex w-full max-w-xl flex-col border-l border-line'
            : 'left-1/2 top-1/2 w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-xl p-6',
          className
        )}
      >
        <div className={cn('flex items-start justify-between gap-4', side === 'right' && 'border-b border-line px-6 py-5')}>
          <div>
            <DialogPrimitive.Title className="text-xl font-bold text-ink">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-1 text-sm text-muted">{description}</DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close aria-label={closeLabel} className="rounded-sm p-1.5 text-muted hover:bg-soft hover:text-ink">
            <X className="size-5" />
          </DialogPrimitive.Close>
        </div>
        <div className={cn(side === 'right' ? 'flex-1 overflow-y-auto px-6 py-5' : 'mt-5')}>{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

/* ---------- Dropdown menu ---------- */
export const Menu = MenuPrimitive.Root;
export const MenuTrigger = MenuPrimitive.Trigger;
export function MenuContent({className, ...props}: ComponentProps<typeof MenuPrimitive.Content>) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        sideOffset={6}
        align="end"
        className={cn('z-50 min-w-48 rounded-md border border-line bg-surface p-1.5 shadow-float', className)}
        {...props}
      />
    </MenuPrimitive.Portal>
  );
}
export function MenuItem({className, danger, ...props}: ComponentProps<typeof MenuPrimitive.Item> & {danger?: boolean}) {
  return (
    <MenuPrimitive.Item
      className={cn(
        'flex cursor-pointer items-center gap-2 rounded-sm px-3 py-2 text-sm outline-none data-[highlighted]:bg-pink-100 data-[highlighted]:text-brand [&_svg]:size-4',
        danger ? 'text-danger data-[highlighted]:bg-danger-50 data-[highlighted]:text-danger' : 'text-ink',
        className
      )}
      {...props}
    />
  );
}
export const MenuSeparator = () => <MenuPrimitive.Separator className="my-1 h-px bg-line" />;
export const MenuLabel = ({children}: {children: ReactNode}) => (
  <MenuPrimitive.Label className="px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-muted">{children}</MenuPrimitive.Label>
);

/* ---------- Accordion ---------- */
export const Accordion = AccordionPrimitive.Root;
export function AccordionItem({question, children, value}: {question: ReactNode; children: ReactNode; value: string}) {
  return (
    <AccordionPrimitive.Item value={value} className="group rounded-lg border border-line bg-surface transition-shadow data-[state=open]:shadow-card">
      <AccordionPrimitive.Header>
        <AccordionPrimitive.Trigger className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-base font-semibold text-ink">
          {question}
          <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-full bg-pink-100 text-lg text-brand transition-transform duration-300 group-data-[state=open]:rotate-45">+</span>
        </AccordionPrimitive.Trigger>
      </AccordionPrimitive.Header>
      <AccordionPrimitive.Content className="overflow-hidden px-5 pb-5 text-[15px] text-text data-[state=closed]:hidden">
        {children}
      </AccordionPrimitive.Content>
    </AccordionPrimitive.Item>
  );
}

/* ---------- Tooltip ---------- */
export function Tooltip({content, children}: {content: ReactNode; children: ReactNode}) {
  return (
    <TooltipPrimitive.Provider delayDuration={200}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content sideOffset={6} className="z-50 max-w-72 rounded-sm bg-ink px-3 py-2 text-xs leading-5 text-white shadow-float">
            {content}
            <TooltipPrimitive.Arrow className="fill-ink" />
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}
